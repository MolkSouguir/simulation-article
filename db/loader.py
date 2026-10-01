"""
db/loader.py

Loads the fleet configuration from the database into database.db_machines.

Everything a machine needs (cost profile, PM schedule, parts) is loaded in one
query, then detached from the session so the objects behave like plain Python
objects and can be deep-copied by the simulation.

Call load_config() once before running any simulation.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import joinedload
from sqlalchemy.orm import make_transient
from sqlalchemy.orm.attributes import set_committed_value

from db.session import get_session
from db.models import (
    MachineModel,
    SparePartModel,
    MaintenanceCostDataModel,
    PreventiveMaintenanceModel,
    PMCycleYearModel,
    PMCycleYearPartModel,
    MachineTypeEnum,
)
import database


def load_config() -> None:
    """
    Fill database.db_machines from the database. The list is cleared first,
    so calling this twice doesn't load the machines twice.
    """
    database.db_machines.clear()

    with get_session() as session:
        # Load everything up front: nothing can be fetched once the session is closed.
        db_machines: list[MachineModel] = (
            session.query(MachineModel)
            .options(
                joinedload(MachineModel.maintenance_cost_data),  # type: ignore[arg-type]
                joinedload(MachineModel.preventive_maintenance)  # type: ignore[arg-type]
                    .joinedload(PreventiveMaintenanceModel.cycle_years)  # type: ignore[arg-type]
                    .joinedload(PMCycleYearModel.parts),  # type: ignore[arg-type]
                joinedload(MachineModel.spare_parts)  # type: ignore[arg-type]
                    .joinedload(SparePartModel.maintenance_cost_data),  # type: ignore[arg-type]
            )
            .order_by(MachineModel.purchase_year)  # type: ignore[arg-type]
            .all()
        )

        # Detach everything. expunge_all() takes the objects out of the session,
        # make_transient() also clears their identity and session link, which
        # deepcopy needs.
        session.expunge_all()

        # Shared objects (a cost profile used by many machines) are detached once.
        already_detached: set[int] = set()

        def _detach(model_object) -> None:
            if model_object is None or id(model_object) in already_detached:
                return
            already_detached.add(id(model_object))
            make_transient(model_object)

        for machine in db_machines:
            _detach(machine.maintenance_cost_data)
            schedule = machine.preventive_maintenance
            if schedule is not None:
                for cycle_year in schedule.cycle_years:
                    for cycle_year_part in cycle_year.parts:
                        _detach(cycle_year_part)
                    _detach(cycle_year)
                _detach(schedule)
            for part in machine.spare_parts:
                _detach(part.maintenance_cost_data)
                _detach(part)
            _detach(machine)

    # Prepare the simulation state and register the machines.
    for machine in db_machines:
        machine.init_simulation_state()
        for part in machine.spare_parts:
            # Link the part back to its machine without firing the relationship
            # event. A plain `part.machine = machine` also appends the part to
            # machine.spare_parts, which already holds it, so every part was
            # listed twice: drawn twice for failures and aged twice as fast.
            set_committed_value(part, "machine", machine)
            part.init_simulation_state()
        database.db_machines.append(machine)

    print(f"[loader] Loaded {len(database.db_machines)} machines from database.")
