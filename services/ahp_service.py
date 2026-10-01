"""
services/ahp_service.py

Runs a full decision: simulate every configuration, rank the alternatives with
AHP, TOPSIS or ELECTRE II, compute the statistics, and save the alternatives
and the decision. This is what POST /api/simulation/run calls.

Usage:
    from services.ahp_service import run_ahp

    result = run_ahp(
        configurations=[
            {"machine_number": 38, "replacement_period": 7, ...},
            ...
        ],
        criteria_config=[
            {"name": "Availability normal", "attribute_name": "normal_availability", ...},
            ...
        ],
        simulation_number=100,
        period=15,
        run_sensitivity=True,
    )
"""
from __future__ import annotations

import random
import uuid
from typing import Any

import numpy as np

from classes.criteria import Criteria
from classes.decision import DecisionMaking
from classes.decision_method_type import DecisionMethodType
from db.session import get_session
from sqlmodel import col
from db.models import CriteriaModel, DecisionModel, DecisionMethodTypeEnum
from db.persistence import persist_alternative, persist_alternatives
from services.simulation_service import run_simulation


def _attach_hours_criterion(alternative: Any, attribute_name: str, threshold: int, period: float) -> None:
    """
    Turn a daily-hours criterion into its score, on the alternative itself.

    Before the simulation, the attribute holds what the user entered: target
    hours per day. It is replaced by worked / scheduled hours, a 0 to 1 score
    like the other availabilities, and the raw hours are kept in
    `<attribute>_worked` and `<attribute>_scheduled` for display. If the
    criterion wasn't requested, the score is simply 0.
    """
    from functions.helper_functions import calculate_session_hours

    target_hours = getattr(alternative, attribute_name, None)
    if not isinstance(target_hours, (int, float)) or target_hours <= 0:
        setattr(alternative, attribute_name, 0.0)
        return

    hours = calculate_session_hours(
        events=alternative.simulations[0].events,
        total_machines=alternative.machine_number,
        threshold=threshold,
        period=period,
        session_days=alternative.session_days,
        shift_durations=[target_hours],
    )
    scheduled = hours["scheduled_hours"]
    setattr(alternative, f"{attribute_name}_worked", hours["worked_hours"])
    setattr(alternative, f"{attribute_name}_scheduled", scheduled)
    setattr(alternative, attribute_name, hours["worked_hours"] / scheduled if scheduled > 0 else 0.0)


def build_criteria(criteria_config: list[dict]) -> list[Criteria]:
    """Criteria objects from their settings (name, attribute_name, minimize)."""
    criteria = []
    for criterion_config in criteria_config:
        criteria.append(Criteria(
            name=criterion_config["name"],
            score=0.0,
            weight=0.0,
            minimize=criterion_config.get("minimize", False),
            attribute_name=criterion_config["attribute_name"],
        ))
    return criteria


def run_decision(
    configurations: list[dict[str, Any]],
    criteria_config: list[dict[str, Any]],
    method: str = "AHP",
    pairwise_matrix: np.ndarray | None = None,
    direct_weights: list[float] | None = None,
    simulation_number: int = 100,
    period: int = 15,
    wd: str = "m",
    run_sensitivity: bool = False,
    persist: bool = True,
    seed: int = 42,
    base_year: int | None = None,
    parallel: bool = False,
    max_workers: int | None = None,
    confidence_level: float = 0.95,
    bootstrap_samples: int = 500,
) -> dict[str, Any]:
    """
    Simulate every configuration, rank them, compute the statistics and save the result.

    configurations: one dict per alternative. criteria_config: name,
    attribute_name, minimize, and optionally input_type (only used in the
    parameter table). method is "AHP", "TOPSIS" or "ELECTRE2": AHP needs
    pairwise_matrix (the expert's criteria matrix) and uses wd to derive the
    weights ('m', 'g' or 'me'). The other two need direct_weights, one per
    criterion.

    run_sensitivity adds the full one-at-a-time weight sensitivity (AHP only).
    bootstrap_samples controls the ranking robustness (0 turns it off).

    Returns a dict with alternatives, criteria, ahp_results (the result of the
    chosen method, whatever it is), sensitivity_results, db_decision_id,
    statistics, bootstrap, cost_ci_ranking, parameter_table and
    confidence_level.
    """
    import database
    from datetime import date
    database.base_year = base_year if base_year else date.today().year
    random.seed(seed)

    # Simulate every alternative
    alternatives = []
    for alternative_number, config in enumerate(configurations, start=1):
        name = config.get("name", f"alternative-{alternative_number}")
        machine_number = config["machine_number"]
        replacement_period = config["replacement_period"]
        normal_threshold = config.get("normal_threshold", machine_number)
        crisis_threshold = config.get("crisis_threshold", machine_number)
        machine_type = config.get("machine_type", "ventilator")
        session_days = config.get("session_days", None)
        shift_durations = config.get("shift_durations", None)

        simulation_keys = {"name", "machine_number", "replacement_period",
                           "normal_threshold", "crisis_threshold", "machine_type",
                           "session_days", "shift_durations"}

        # Everything else (qualitative scores, daily hours) goes on the alternative
        extra = {key: value for key, value in config.items() if key not in simulation_keys}

        alternative, _ = run_simulation(
            name=name,
            machine_number=machine_number,
            replacement_period=replacement_period,
            period=period,
            simulation_number=simulation_number,
            normal_threshold=normal_threshold,
            crisis_threshold=crisis_threshold,
            machine_type=machine_type,
            session_days=session_days,
            shift_durations=shift_durations,
            persist=False,
            parallel=parallel,
            max_workers=max_workers,
            **extra,
        )

        # The daily-hours criteria can only be scored now that the events of
        # the first run exist.
        _attach_hours_criterion(alternative, "normal_hours_availability", normal_threshold, period)
        _attach_hours_criterion(alternative, "crisis_hours_availability", crisis_threshold, period)

        alternatives.append(alternative)
        print(f"[AHP] Simulated {name}: cost={alternative.total_cost:,.0f} "
              f"avail_normal={alternative.normal_availability:.1f}%")

    criteria = build_criteria(criteria_config)

    # Rank with the chosen method
    method_enum = DecisionMethodType(method.upper())
    decision = DecisionMaking(decision_method=method_enum)
    for alternative in alternatives:
        decision.add_alternative(alternative)
    for criterion in criteria:
        decision.add_criteria(criterion)

    if method_enum == DecisionMethodType.TOPSIS:
        if not direct_weights:
            raise ValueError("direct_weights required for TOPSIS")
        ahp_results = decision.TOPSIS(weights=np.array(direct_weights, dtype=float))
        print("[TOPSIS] Ranking complete.")
    elif method_enum == DecisionMethodType.ELECTRE2:
        if not direct_weights:
            raise ValueError("direct_weights required for ELECTRE2")
        ahp_results = decision.ELECTRE2(weights=np.array(direct_weights, dtype=float))
        print("[ELECTRE2] Ranking complete.")
    else:
        if pairwise_matrix is None:
            raise ValueError("pairwise_matrix required for AHP")
        ahp_results = decision.AHP(pairwise_matrix=pairwise_matrix, wd=wd)
        consistency_ratio = ahp_results["consistency_ratio"]
        print(f"[AHP] Consistency ratio: {consistency_ratio:.4f} "
              f"({'OK' if consistency_ratio < 0.1 else 'INCONSISTENT'})")

    sensitivity_results = None
    if run_sensitivity and method_enum == DecisionMethodType.AHP:
        from analysis.sensitivity import run_full_sensitivity_analysis
        sensitivity_results = run_full_sensitivity_analysis(alternatives, criteria)

    # Statistics and the parameter table. They only read the per-run numbers
    # already stored on each alternative, so the simulation and its random
    # numbers are not affected (the bootstrap uses its own generator).
    from analysis.statistics import summarize_alternatives, bootstrap_ranking, cost_ci_ranking
    from analysis.parameter_table import build_parameter_table

    statistics = summarize_alternatives(alternatives, confidence=confidence_level, seed=seed)
    bootstrap = bootstrap_ranking(
        alternatives, criteria, method_enum,
        pairwise_matrix=pairwise_matrix, direct_weights=direct_weights, wd=wd,
        samples=bootstrap_samples, seed=seed, confidence=confidence_level,
    )
    cost_ci_ranking_result = cost_ci_ranking(
        alternatives, criteria, method_enum, statistics,
        pairwise_matrix=pairwise_matrix, direct_weights=direct_weights, wd=wd,
        confidence=confidence_level,
    )
    parameter_table = build_parameter_table(
        alternatives, criteria, method_enum, ahp_results,
        period=period, simulation_number=simulation_number, seed=seed,
        base_year=database.base_year, confidence_level=confidence_level,
        bootstrap_samples=bootstrap_samples,
        pairwise_matrix=pairwise_matrix, direct_weights=direct_weights, wd=wd,
        parallel=parallel, max_workers=max_workers,
        criteria_input_types={
            criterion_config["attribute_name"]: criterion_config["input_type"]
            for criterion_config in criteria_config if criterion_config.get("input_type")
        },
    )
    if bootstrap:
        print(f"[stats] {confidence_level:.0%} CI + convergence for {len(alternatives)} alternatives; "
              f"bootstrap ranks over {bootstrap['samples']} draws.")

    # Save the alternatives and the decision
    db_decision_id = None
    if persist:
        persist_alternatives(alternatives)
        db_decision_id = _persist_decision(
            alternatives=alternatives,
            criteria=criteria,
            decision_results=ahp_results,
            method=method_enum,
        )
        print(f"[DB] Persisted decision (id={db_decision_id}).")

    return {
        "alternatives": alternatives,
        "criteria": criteria,
        "ahp_results": ahp_results,
        "sensitivity_results": sensitivity_results,
        "db_decision_id": db_decision_id,
        "statistics": statistics,
        "bootstrap": bootstrap,
        "cost_ci_ranking": cost_ci_ranking_result,
        "parameter_table": parameter_table,
        "confidence_level": confidence_level,
    }


def _persist_decision(alternatives, criteria, decision_results, method=None) -> uuid.UUID:
    """Save the criteria and the decision, linked to the alternatives just saved."""
    ranking = decision_results["ranking"]
    best_alternative_name = ranking.iloc[0]["Alternative"]

    with get_session() as session:
        criteria_rows = []
        for criterion in criteria:
            criterion_row = CriteriaModel(
                name=criterion.name,
                attribute_name=criterion.attribute_name,
                weight=float(criterion.weight),
                minimize=criterion.minimize,
            )
            session.add(criterion_row)
            criteria_rows.append(criterion_row)
        session.flush()

        # Alternatives are found again by name. The ids are random UUIDs, so
        # "latest id" isn't really the latest row when names repeat (known issue).
        from db.models import AlternativeModel
        best_alternative_row = (
            session.query(AlternativeModel)
            .filter(AlternativeModel.name == best_alternative_name)
            .order_by(col(AlternativeModel.id).desc())
            .first()
        )

        consistency_ratio = decision_results.get("consistency_ratio")
        decision_row = DecisionModel(
            method=DecisionMethodTypeEnum(method.value if method else "AHP"),
            consistency_ratio=float(consistency_ratio) if consistency_ratio is not None else None,
            best_alternative_id=best_alternative_row.id if best_alternative_row else None,
        )
        session.add(decision_row)
        session.flush()

        for criterion_row in criteria_rows:
            decision_row.criteria.append(criterion_row)

        for alternative in alternatives:
            alternative_row = (
                session.query(AlternativeModel)
                .filter(AlternativeModel.name == alternative.name)
                .order_by(col(AlternativeModel.id).desc())
                .first()
            )
            if alternative_row:
                decision_row.alternatives.append(alternative_row)

        session.flush()
        decision_id = decision_row.id

    return decision_id


# Older name, still used by analysis/ahp.py
def run_ahp(configurations, criteria_config, pairwise_matrix, **kwargs):
    return run_decision(
        configurations=configurations,
        criteria_config=criteria_config,
        method="AHP",
        pairwise_matrix=pairwise_matrix,
        **kwargs,
    )
