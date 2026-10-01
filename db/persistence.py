"""
db/persistence.py

Saves simulation results to the database once a run is finished.

The simulation classes (Alternative, Simulation, Event) don't know about the
database. This module is the only place that deals with both.

Usage (from services/simulation_service.py):
    from db.persistence import persist_alternative
    alternative_row = persist_alternative(alternative)
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from db.session import get_session
from db.models import (
    AlternativeModel,
    SimulationModel,
    EventModel,
    EventTypeEnum,
)

if TYPE_CHECKING:
    from classes.alternative import Alternative
    from classes.simulation import Simulation
    from classes.parallel import SimulationResult


def persist_alternatives(alternatives: list, persist_events: bool = False) -> list[AlternativeModel]:
    """Save several alternatives in one transaction."""
    alternative_rows = []
    with get_session() as session:
        for alternative in alternatives:
            alternative_row = _build_alternative_model(alternative)
            session.add(alternative_row)
            session.flush()
            for simulation in alternative.simulations:
                _persist_simulation(session, simulation, alternative_row, persist_events=persist_events)
            alternative_rows.append(alternative_row)
        session.commit()
        for alternative_row in alternative_rows:
            session.refresh(alternative_row)
    print(f"[DB] Persisted {len(alternative_rows)} alternatives in one transaction.")
    return alternative_rows


def _build_alternative_model(alternative: Alternative) -> AlternativeModel:
    return AlternativeModel(
        name=alternative.name,
        machine_number=alternative.machine_number,
        replacement_period=alternative.replacement_period,
        period=alternative.period,
        simulation_number=alternative.simulation_number,
        normal_threshold=alternative.normal_threshold,
        crisis_threshold=alternative.crisis_threshold,
        total_cost=alternative.total_cost,
        purchase_cost=alternative.purchase_cost,
        corrective_maintenance_cost=alternative.corrective_maintenance_cost,
        preventive_maintenance_cost=alternative.preventive_maintenance_cost,
        normal_availability=alternative.normal_availability,
        crisis_availability=alternative.crisis_availability,
        clinical_features=getattr(alternative, "clinical_features", None),
        staff_satisfaction=getattr(alternative, "staff_satisfaction", None),
        logistics_procurement=getattr(alternative, "logistics_procurement", None),
    )


def persist_alternative(alternative: Alternative) -> AlternativeModel:
    """Save one finished alternative with its runs. Returns the saved row (with its id)."""
    with get_session() as session:
        alternative_row = _build_alternative_model(alternative)
        session.add(alternative_row)
        session.flush()  # gives alternative_row an id for the runs below

        for simulation in alternative.simulations:
            _persist_simulation(session, simulation, alternative_row, persist_events=False)

        session.commit()
        session.refresh(alternative_row)

    print(f"[DB] Persisted alternative '{alternative.name}' (id={alternative_row.id}) "
          f"with {len(alternative.simulations)} simulation(s).")
    return alternative_row


def _persist_simulation(session, simulation: "Simulation | SimulationResult", alternative_row: AlternativeModel, persist_events: bool = False) -> SimulationModel:
    """Save one run, and its events if persist_events is set."""
    simulation_row = SimulationModel(
        simulation_number=simulation.simulation_number,
        purchase_cost=simulation.purchase_cost,
        corrective_maintenance_cost=simulation.corrective_maintenance_cost,
        preventive_maintenance_cost=simulation.preventive_maintenance_cost,
        normal_availability=simulation.normal_availability,
        crisis_availability=simulation.crisis_availability,
        alternative_id=alternative_row.id,
        alternative=alternative_row,
    )
    session.add(simulation_row)
    session.flush()

    if not persist_events:
        return simulation_row

    event_rows = []
    for event in simulation.events:
        item = event.maintenance_item
        try:
            # EventType values are declared as 1-tuples, so unwrap them.
            event_type_value = (
                event.event_type.value[0]
                if isinstance(event.event_type.value, tuple)
                else event.event_type.value
            )
            event_rows.append({
                "event_type": EventTypeEnum(event_type_value),
                "start_time": event.start_time,
                "end_time": event.end_time,
                "duration": event.duration,
                "cost": event.cost,
                "description": event.description,
                "maintenance_item_name": item.name if item else None,
                "maintenance_item_code": item.code if item else None,
                "simulation_id": simulation_row.id,
            })
        except Exception:
            continue

    if event_rows:
        session.bulk_insert_mappings(EventModel, event_rows)
    return simulation_row
