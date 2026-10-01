"""
analysis/parameter_table.py

The table of every input that went into a decision run, for the report.

The fleet is read the way the simulation sees it (database.db_machines, the
youngest machines first for each alternative), so the table shows what was
actually simulated, not just what is in the database. The result is a plain
dict, one key per section, that analysis/report.py turns into Excel sheets.
"""
from __future__ import annotations

import inspect
from collections import Counter, OrderedDict
from operator import attrgetter
from typing import Any, Sequence

import numpy as np

import database
from analysis.statistics import METRICS, CI_BOOTSTRAP_SAMPLES
from classes.criteria import Criteria
from classes.decision import DecisionMaking
from classes.decision_method_type import DecisionMethodType


def _type_name(machine_type: Any) -> str:
    return str(getattr(machine_type, "value", machine_type))


def _cost_profile_row(cost_profile: Any) -> dict[str, Any]:
    return {
        "name": cost_profile.name,
        "hourly_labor_cost": cost_profile.hourly_labor_cost,
        "corrective_maintenance_hours": cost_profile.corrective_maintenance_hours,
        "corrective_maintenance_additional_downtime_hours": cost_profile.corrective_maintenance_additional_downtime_hours,
        "preventive_maintenance_hours": cost_profile.preventive_maintenance_hours,
    }


def _fleet_sections(machine_types: Sequence[str]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Machine groups, spare part groups, cost profiles and PM programmes of the given machine types."""
    machines = [machine for machine in database.db_machines if _type_name(machine.machine_type) in machine_types]

    # Identical machines (and parts) are grouped into one row with a count
    cohorts: "OrderedDict[tuple, int]" = OrderedDict()
    parts: "OrderedDict[tuple, int]" = OrderedDict()
    cost_profiles: "OrderedDict[Any, dict]" = OrderedDict()
    pm_programmes: "OrderedDict[Any, Any]" = OrderedDict()

    for machine in sorted(machines, key=lambda machine: (_type_name(machine.machine_type), -machine.purchase_year)):
        cost_profile = machine.maintenance_cost_data
        schedule = machine.preventive_maintenance
        cohort_key = (
            _type_name(machine.machine_type), machine.purchase_year, machine.purchase_cost, machine.eta, machine.beta,
            cost_profile.name if cost_profile else None, schedule.name if schedule else None,
        )
        cohorts[cohort_key] = cohorts.get(cohort_key, 0) + 1
        if cost_profile is not None:
            cost_profiles.setdefault(
                cost_profile.id, {**_cost_profile_row(cost_profile), "used_by": set()}
            )["used_by"].add(f"machine:{_type_name(machine.machine_type)}")
        if schedule is not None:
            pm_programmes.setdefault(schedule.id, schedule)

        for part in machine.spare_parts:
            part_cost_profile = part.maintenance_cost_data
            part_key = (
                _type_name(machine.machine_type), _type_name(part.spare_part_type), part.eta, part.beta,
                part.purchase_cost, part_cost_profile.name if part_cost_profile else None,
            )
            parts[part_key] = parts.get(part_key, 0) + 1
            if part_cost_profile is not None:
                cost_profiles.setdefault(
                    part_cost_profile.id, {**_cost_profile_row(part_cost_profile), "used_by": set()}
                )["used_by"].add(f"part:{_type_name(part.spare_part_type)}")

    fleet_rows = [
        {
            "machine_type": cohort_key[0], "purchase_year": cohort_key[1], "purchase_cost": cohort_key[2],
            "eta": cohort_key[3], "beta": cohort_key[4], "cost_profile": cohort_key[5], "pm_programme": cohort_key[6],
            "count": count,
        }
        for cohort_key, count in cohorts.items()
    ]
    part_rows = [
        {
            "machine_type": part_key[0], "spare_part_type": part_key[1], "eta": part_key[2], "beta": part_key[3],
            "purchase_cost": part_key[4], "cost_profile": part_key[5], "count": count,
        }
        for part_key, count in parts.items()
    ]
    cost_profile_rows = [
        {**{key: value for key, value in row.items() if key != "used_by"}, "used_by": sorted(row["used_by"])}
        for row in cost_profiles.values()
    ]
    pm_rows = []
    for schedule in pm_programmes.values():
        cycle_years = schedule.preventive_maintenance_cycle_years
        pm_rows.append({
            "name": schedule.name,
            "years_interval": schedule.years_interval,
            "cycle_length_years": schedule.maintenance_cycle,
            "cycle_years": [
                {
                    "order": cycle_year.order,
                    "preventive_maintenance_hours": cycle_year.preventive_maintenance_hours,
                    "hourly_labor_cost": cycle_year.hourly_labor_cost,
                    "pm_year_cost": cycle_year.pm_year_cost,
                    "parts_replaced": [_type_name(pm_part.spare_part_type) for pm_part in cycle_year.preventive_maintenance_parts],
                }
                for cycle_year in cycle_years
            ],
        })
    return fleet_rows, part_rows, cost_profile_rows, pm_rows


def _cohorts_used(machine_type: str, machine_number: int) -> list[dict[str, Any]]:
    """The machines an alternative actually gets, chosen like Simulation.__init__ does (youngest first)."""
    typed_machines = [machine for machine in database.db_machines if _type_name(machine.machine_type) == machine_type]
    typed_machines.sort(key=attrgetter("age"))
    chosen = typed_machines[:machine_number]
    counter = Counter((machine.purchase_year, machine.purchase_cost) for machine in chosen)
    return [
        {"purchase_year": purchase_year, "purchase_cost": purchase_cost, "count": count}
        for (purchase_year, purchase_cost), count in sorted(counter.items(), key=lambda item: -item[0][0])
    ]


def _electre2_defaults() -> dict[str, float]:
    """The ELECTRE II thresholds, read from the method's default arguments."""
    parameters = inspect.signature(DecisionMaking.ELECTRE2).parameters
    return {name: parameters[name].default for name in ("c_plus", "c_minus", "d_threshold")}


def build_parameter_table(
    alternatives: Sequence[Any],
    criteria: Sequence[Criteria],
    method: DecisionMethodType,
    ahp_results: dict[str, Any],
    *,
    period: int,
    simulation_number: int,
    seed: int,
    base_year: int,
    confidence_level: float,
    bootstrap_samples: int,
    pairwise_matrix: np.ndarray | None = None,
    direct_weights: Sequence[float] | None = None,
    wd: str = "m",
    parallel: bool = False,
    max_workers: int | None = None,
    criteria_input_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Every input that determined this run, in one dict."""
    machine_types = sorted({_type_name(alternative.machine_type) for alternative in alternatives})
    fleet_rows, part_rows, cost_profile_rows, pm_rows = _fleet_sections(machine_types)

    qualitative_attributes = [criterion.attribute_name for criterion in criteria if criterion.attribute_name not in METRICS]

    alternative_rows = []
    for alternative in alternatives:
        machine_type = _type_name(alternative.machine_type)
        alternative_rows.append({
            "name": alternative.name,
            "machine_type": machine_type,
            "machine_number": alternative.machine_number,
            "replacement_period": alternative.replacement_period,
            "normal_threshold": alternative.normal_threshold,
            "crisis_threshold": alternative.crisis_threshold,
            "standby_pool": max(0, alternative.machine_number - alternative.normal_threshold),
            "session_days": list(alternative.session_days),
            "shift_durations": list(alternative.shift_durations),
            "scores": {attribute: getattr(alternative, attribute, None) for attribute in qualitative_attributes},
            "cohorts_used": _cohorts_used(machine_type, alternative.machine_number),
        })

    weights = ahp_results.get("weights", {}) or {}
    criteria_rows = []
    for criterion in criteria:
        criteria_rows.append({
            "name": criterion.name,
            "attribute_name": criterion.attribute_name,
            "input_type": (criteria_input_types or {}).get(criterion.attribute_name),
            "minimize": bool(criterion.minimize),
            "weight": float(weights.get(criterion.name, criterion.weight or 0.0)),
        })

    decision: dict[str, Any] = {
        "method": method.value,
        "criteria": criteria_rows,
        "consistency_ratio": ahp_results.get("consistency_ratio"),
        "lambda_max": ahp_results.get("lambda_max"),
        "random_index": ahp_results.get("random_index"),
        "pairwise_matrix": None,
        "direct_weights": None,
        "ahp_weight_derivation": wd if method == DecisionMethodType.AHP else None,
        "electre2": _electre2_defaults() if method == DecisionMethodType.ELECTRE2 else None,
    }
    if method == DecisionMethodType.AHP and pairwise_matrix is not None:
        criteria_names = [criterion.name for criterion in criteria]
        decision["pairwise_matrix"] = {
            "criteria": criteria_names,
            "rows": [[float(value) for value in matrix_row] for matrix_row in np.asarray(pairwise_matrix, dtype=float)],
        }
    elif direct_weights is not None:
        decision["direct_weights"] = [float(weight) for weight in direct_weights]

    return {
        "run": {
            "period_years": period,
            "horizon_convention": "half-open [0, period): events at t == period are not dispatched",
            "simulation_number": simulation_number,
            "seed": seed,
            "base_year": base_year,
            "inflation_rate": database.inflation_rate,
            "confidence_level": confidence_level,
            "confidence_interval": f"bootstrap percentile, {CI_BOOTSTRAP_SAMPLES} resamples",
            "bootstrap_samples": bootstrap_samples,
            "parallel": parallel,
            "max_workers": max_workers,
            "machine_types": machine_types,
            "fleet_loaded": {
                machine_type: sum(row["count"] for row in fleet_rows if row["machine_type"] == machine_type)
                for machine_type in machine_types
            },
        },
        "alternatives": alternative_rows,
        "fleet": fleet_rows,
        "spare_parts": part_rows,
        "cost_profiles": cost_profile_rows,
        "pm_programmes": pm_rows,
        "decision": decision,
    }
