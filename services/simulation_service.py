"""
services/simulation_service.py

Runs one alternative: loads the fleet if needed, runs its Monte Carlo
simulations (creating the Alternative does that), optionally saves the
results, and returns the Alternative with its database id.

Usage:
    from services.simulation_service import run_simulation

    alternative, db_id = run_simulation(
        name="Alt-1",
        machine_number=38,
        replacement_period=7,
        period=15,
        simulation_number=100,
        normal_threshold=36,
        crisis_threshold=44,
    )
    print(alternative.total_cost, db_id)
"""
from __future__ import annotations

import uuid
import database
from db.loader import load_config
from db.persistence import persist_alternative
from classes.alternative import Alternative
from db.models import MachineTypeEnum


def run_simulation(
    name: str,
    machine_number: int,
    replacement_period: int,
    period: int,
    simulation_number: int,
    normal_threshold: int = 36,
    crisis_threshold: int = 44,
    machine_type: str | MachineTypeEnum = "ventilator",
    session_days: list | None = None,
    shift_durations: list[float] | None = None,
    persist: bool = True,
    parallel: bool = False,
    max_workers: int | None = None,
    **extra_criteria,
) -> tuple[Alternative, uuid.UUID | None]:
    """
    Simulate one alternative and return (alternative, database id).

    machine_number is the fleet size, replacement_period the years between
    replacements, period the horizon in years and simulation_number the number
    of Monte Carlo runs. normal_threshold and crisis_threshold are the
    headcounts for normal and crisis availability.

    With parallel=True, runs 2..N go to worker processes (max_workers of
    them, all CPUs by default). Only run 1 keeps its events, see
    classes/parallel.py. Extra keyword arguments (clinical_features=10,
    staff_satisfaction=7.5, ...) become attributes of the Alternative.

    The id is None when persist is False.
    """
    # A new process starts with an empty fleet
    if not database.db_machines:
        load_config()

    machine_type_enum = MachineTypeEnum(machine_type) if isinstance(machine_type, str) else machine_type

    alternative = Alternative(
        name=name,
        machine_number=machine_number,
        replacement_period=replacement_period,
        period=period,
        simulation_number=simulation_number,
        normal_threshold=normal_threshold,
        crisis_threshold=crisis_threshold,
        machine_type=machine_type_enum,
        session_days=session_days,
        shift_durations=shift_durations,
        parallel=parallel,
        max_workers=max_workers,
        **extra_criteria,
    )

    db_id = None
    if persist:
        alternative_row = persist_alternative(alternative)
        db_id = alternative_row.id

    return alternative, db_id
