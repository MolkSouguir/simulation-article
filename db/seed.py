"""
db/seed.py

Seeds the reference fleet configuration (machine types, cost profiles, PM
programmes, machines, spare parts) and the ventilator scenario profile into
the database.

    python -m db.seed

Careful: running it again empties the fleet configuration and every
simulation output table (alternative, simulation, event, decision, criteria)
before inserting. Scenario profiles, saved runs and machine types are kept
(the types and the ventilator scenario are only added if missing).

The values match the configuration used for the study on 2026-09-19 (after
tuning it in the app and on the Tools page), so a fresh database gives the
same fleet the reported results came from.
"""
import sys
from pathlib import Path

# So the script also works when run as a file, not only with -m
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import SQLModel
from db.session import ensure_postgres_ready, get_session, get_engine
from db.models import (
    MaintenanceCostDataModel,
    MachineModel,
    MachineTypeModel,
    SparePartModel,
    PreventiveMaintenanceModel,
    PMCycleYearModel,
    PMCycleYearPartModel,
    ScenarioProfileModel,
    MachineTypeEnum,
    MachineStatusEnum,
    SparePartTypeEnum,
    SparePartStatusEnum,
)


MACHINE_TYPES = ["ventilator", "dialysis"]


def seed_machine_types(session) -> None:
    """
    Add the machine types used below if they are missing. machine.machine_type
    points to machine_type.name, so these rows must exist before the machines
    (on a fresh database nothing creates them until the API starts). Types that
    are already there, including ones added by users, are left alone.
    """
    existing = {machine_type.name for machine_type in session.query(MachineTypeModel).all()}
    added = [name for name in MACHINE_TYPES if name not in existing]
    for name in added:
        session.add(MachineTypeModel(name=name))
    session.flush()
    print(f"[seed] Machine types present: {sorted(existing | set(added))} (added {len(added)}).")


def seed_cost_data(session) -> dict:
    """
    Insert the cost profiles. Returns them by label so the machines and parts
    below can be linked to them.
    """
    profiles = {
        # Repair of a ventilator itself. Only used if a ventilator gets η and
        # β above 0. With η = 0 (below) ventilator failures come from their
        # parts, which have their own profiles. It is linked anyway so that a
        # later β/η fit from the Tools page doesn't hit the check in
        # handle_failure that skips failures without cost data.
        "machine": MaintenanceCostDataModel(
            name="Ventilator Machine Cost",
            hourly_labor_cost=60,
            corrective_maintenance_hours=0.5,
            corrective_maintenance_additional_downtime_hours=0.5,
            preventive_maintenance_hours=0,
        ),
        # Labour rate from the GMAO export 6008_combined.xlsx: mean
        # intervention cost 103.63 € over a mean repair time of 1.53 h gives
        # 71.81 €/h. Repairs were set in the app to 3.0 h of labour plus 1.0 h
        # of extra downtime. The PM duration (3.70 h) lives on the PM cycle
        # year, so preventive_maintenance_hours stays 0 here.
        "dialysis_machine": MaintenanceCostDataModel(
            name="Dialysis Machine Cost",
            hourly_labor_cost=71.81,
            corrective_maintenance_hours=3.0,
            corrective_maintenance_additional_downtime_hours=1.0,
            preventive_maintenance_hours=0,
        ),
        "battery": MaintenanceCostDataModel(
            name="Battery",
            hourly_labor_cost=60,
            corrective_maintenance_hours=2,
            corrective_maintenance_additional_downtime_hours=1.0,
            preventive_maintenance_hours=0,
        ),
        "gasket": MaintenanceCostDataModel(
            name="Gasket",
            hourly_labor_cost=60,
            corrective_maintenance_hours=0.5,
            corrective_maintenance_additional_downtime_hours=1.0,
            preventive_maintenance_hours=0,
        ),
        "filter": MaintenanceCostDataModel(
            name="Filter",
            hourly_labor_cost=60,
            corrective_maintenance_hours=0.5,
            corrective_maintenance_additional_downtime_hours=1.0,
            preventive_maintenance_hours=0,
        ),
        "sensor": MaintenanceCostDataModel(
            name="Sensor",
            hourly_labor_cost=60,
            corrective_maintenance_hours=1,
            corrective_maintenance_additional_downtime_hours=1.0,
            preventive_maintenance_hours=0,
        ),
        "valve": MaintenanceCostDataModel(
            name="Valve",
            hourly_labor_cost=60,
            corrective_maintenance_hours=2,
            corrective_maintenance_additional_downtime_hours=1.0,
            preventive_maintenance_hours=0,
        ),
        "roulement": MaintenanceCostDataModel(
            name="Roulement",
            hourly_labor_cost=60,
            corrective_maintenance_hours=3,
            corrective_maintenance_additional_downtime_hours=2.0,
            preventive_maintenance_hours=0,
        ),
        "kit_constructor": MaintenanceCostDataModel(
            name="Kit Constructor",
            hourly_labor_cost=60,
            corrective_maintenance_hours=1.5,
            corrective_maintenance_additional_downtime_hours=2.5,
            preventive_maintenance_hours=0,
        ),
    }
    for profile in profiles.values():
        session.add(profile)
    session.flush()  # gives them ids without committing
    print(f"[seed] Inserted {len(profiles)} MaintenanceCostData profiles.")
    return profiles


def seed_pm_program(session) -> PreventiveMaintenanceModel:
    """Insert the ventilator PM programme and its 6 cycle years, and return it."""
    ventilator_pm = PreventiveMaintenanceModel(name="Ventilator PM Cycle", years_interval=1)
    session.add(ventilator_pm)
    session.flush()

    # One entry per cycle year: (PM hours, labour rate, parts replaced)
    cycle_year_defs = [
        (1,   60, [SparePartTypeEnum.GASKET, SparePartTypeEnum.FILTER]),
        (2,   60, [SparePartTypeEnum.GASKET, SparePartTypeEnum.FILTER, SparePartTypeEnum.SENSOR]),
        (2.5, 60, [SparePartTypeEnum.GASKET, SparePartTypeEnum.FILTER, SparePartTypeEnum.BATTERY]),
        (3,   60, [SparePartTypeEnum.GASKET, SparePartTypeEnum.FILTER, SparePartTypeEnum.SENSOR, SparePartTypeEnum.VALVE]),
        (4,   60, [SparePartTypeEnum.GASKET, SparePartTypeEnum.FILTER, SparePartTypeEnum.ROULEMENT]),
        (5,   60, [SparePartTypeEnum.GASKET, SparePartTypeEnum.FILTER, SparePartTypeEnum.SENSOR, SparePartTypeEnum.BATTERY, SparePartTypeEnum.KIT_CONSTRUCTOR]),
    ]

    # Part prices used to compute pm_year_cost (same values as app.py)
    part_costs = {
        SparePartTypeEnum.GASKET: 10,
        SparePartTypeEnum.FILTER: 20,
        SparePartTypeEnum.SENSOR: 260,
        SparePartTypeEnum.BATTERY: 350,
        SparePartTypeEnum.VALVE: 160,
        SparePartTypeEnum.ROULEMENT: 160,
        SparePartTypeEnum.KIT_CONSTRUCTOR: 700,
    }

    for order, (pm_hours, labor_cost, part_types) in enumerate(cycle_year_defs, start=1):
        pm_year_cost = labor_cost * pm_hours + sum(part_costs[part_type] for part_type in part_types)
        cycle_year = PMCycleYearModel(
            order=order,
            preventive_maintenance_hours=pm_hours,
            hourly_labor_cost=labor_cost,
            pm_year_cost=pm_year_cost,
            preventive_maintenance_id=ventilator_pm.id,
        )
        session.add(cycle_year)
        session.flush()

        for part_type in part_types:
            session.add(PMCycleYearPartModel(
                spare_part_type=part_type,
                pm_cycle_year_id=cycle_year.id
            ))

    session.flush()
    print(f"[seed] Inserted PM program '{ventilator_pm.name}' with {len(cycle_year_defs)} cycle years.")
    return ventilator_pm


def seed_pm_program_dialysis(session) -> PreventiveMaintenanceModel:
    """
    Insert the dialysis PM: a single cycle year repeated every year, labour
    only (no parts), 3.70 h and 214.22 € per year.
    """
    dialysis_pm = PreventiveMaintenanceModel(name="Dialysis Annual PM", years_interval=1)
    session.add(dialysis_pm)
    session.flush()

    cycle_year = PMCycleYearModel(
        order=1,
        preventive_maintenance_hours=3.70,
        hourly_labor_cost=round(214.22 / 3.70, 2),
        pm_year_cost=214.22,
        preventive_maintenance_id=dialysis_pm.id,
    )
    session.add(cycle_year)
    session.flush()
    print(f"[seed] Inserted dialysis PM program '{dialysis_pm.name}' with 1 cycle year.")
    return dialysis_pm


def seed_machines(session, cost_profiles: dict, ventilator_pm: PreventiveMaintenanceModel, dialysis_pm: PreventiveMaintenanceModel):
    """
    Insert the machines, with a sensor and a battery on every ventilator.

    45 ventilators, without machine-level failures (η = 0): their failures
    come from the sensor and battery.
      1 to 20:  bought in 2019 for 22 200
      21 to 45: bought in 2010 for 18 575

    75 dialysis machines, with machine-level failures and no spare parts.
      1 to 40:  bought in 2020 for 16 000
      41 to 75: bought in 2013 for 16 000
    """
    BETA_PARTS = 1.8
    # Dialysis Weibull parameters, fitted on the GMAO export with the Tools
    # page (time between failures, maximum likelihood) and used for every unit.
    ETA_DIALYSIS = 0.8
    BETA_DIALYSIS = 2.0

    count = 0

    # Ventilators
    for unit_number in range(1, 46):
        purchase_year = 2019 if unit_number <= 20 else 2010
        purchase_cost = 22200 if unit_number <= 20 else 18575

        machine = MachineModel(
            name=f"Ventilator {unit_number}",
            code=f"V-{unit_number:03d}",
            machine_type=MachineTypeEnum.VENTILATOR,
            purchase_year=purchase_year,
            purchase_cost=purchase_cost,
            status=MachineStatusEnum.ACTIVE,
            eta=0,      # no machine-level failures, the parts fail instead
            beta=0,
            maintenance_cost_data=cost_profiles["machine"],
            preventive_maintenance=ventilator_pm,
        )
        session.add(machine)
        session.flush()

        session.add(SparePartModel(
            name=f"Sensor {unit_number}",
            code=f"SP-SENSR{unit_number}",
            spare_part_type=SparePartTypeEnum.SENSOR,
            purchase_year=purchase_year,
            purchase_cost=70,
            status=SparePartStatusEnum.USED,
            eta=2.25,
            beta=BETA_PARTS,
            machine=machine,
            maintenance_cost_data=cost_profiles["sensor"],
        ))
        session.add(SparePartModel(
            name=f"Battery {unit_number}",
            code=f"SP-BTR{unit_number}",
            spare_part_type=SparePartTypeEnum.BATTERY,
            purchase_year=purchase_year,
            purchase_cost=260,
            status=SparePartStatusEnum.USED,
            eta=3.37,
            beta=BETA_PARTS,
            machine=machine,
            maintenance_cost_data=cost_profiles["battery"],
        ))
        count += 1

    # Dialysis machines
    for unit_number in range(1, 76):
        purchase_year = 2020 if unit_number <= 40 else 2013
        purchase_cost = 16000

        session.add(MachineModel(
            name=f"Dialysis {unit_number}",
            code=f"D-{unit_number:03d}",
            machine_type=MachineTypeEnum.DIALYSIS,
            purchase_year=purchase_year,
            purchase_cost=purchase_cost,
            status=MachineStatusEnum.ACTIVE,
            eta=ETA_DIALYSIS,
            beta=BETA_DIALYSIS,
            maintenance_cost_data=cost_profiles["dialysis_machine"],
            preventive_maintenance=dialysis_pm,
        ))
        count += 1

    session.flush()
    print(f"[seed] Inserted {count} machines (45 ventilators + 75 dialysis).")


def seed_pm_parts(session, cost_profiles: dict):
    """
    Insert one loose part of each type, not attached to any machine. They only
    document the part prices used for the PM costs.
    """
    pm_parts = [
        SparePartModel(
            name="gasket", code="SP-GASKET",
            spare_part_type=SparePartTypeEnum.GASKET,
            purchase_year=2025, purchase_cost=10,
            status=SparePartStatusEnum.USED,
            eta=1.12, beta=1.8,
            maintenance_cost_data=cost_profiles["gasket"],
        ),
        SparePartModel(
            name="filter", code="SP-FILTER",
            spare_part_type=SparePartTypeEnum.FILTER,
            purchase_year=2025, purchase_cost=20,
            status=SparePartStatusEnum.USED,
            eta=1.12, beta=1.8,
            maintenance_cost_data=cost_profiles["filter"],
        ),
        SparePartModel(
            name="sensor", code="SP-SENSR",
            spare_part_type=SparePartTypeEnum.SENSOR,
            purchase_year=2025, purchase_cost=260,
            status=SparePartStatusEnum.USED,
            eta=2.25, beta=1.8,
            maintenance_cost_data=cost_profiles["sensor"],
        ),
        SparePartModel(
            name="battery", code="SP-BTR",
            spare_part_type=SparePartTypeEnum.BATTERY,
            purchase_year=2025, purchase_cost=350,
            status=SparePartStatusEnum.USED,
            eta=3.37, beta=1.8,
            maintenance_cost_data=cost_profiles["battery"],
        ),
        SparePartModel(
            name="valve", code="SP-VALVES",
            spare_part_type=SparePartTypeEnum.VALVE,
            purchase_year=2025, purchase_cost=160,
            status=SparePartStatusEnum.USED,
            eta=4.5, beta=1.8,
            maintenance_cost_data=cost_profiles["valve"],
        ),
        SparePartModel(
            name="roulement", code="SP-ROUL",
            spare_part_type=SparePartTypeEnum.ROULEMENT,
            purchase_year=2025, purchase_cost=160,
            status=SparePartStatusEnum.USED,
            eta=5.62, beta=1.8,
            maintenance_cost_data=cost_profiles["roulement"],
        ),
        SparePartModel(
            name="kit constructor", code="SP-KIT",
            spare_part_type=SparePartTypeEnum.KIT_CONSTRUCTOR,
            purchase_year=2025, purchase_cost=700,
            status=SparePartStatusEnum.USED,
            eta=6.74, beta=1.8,
            maintenance_cost_data=cost_profiles["kit_constructor"],
        ),
    ]
    for part in pm_parts:
        session.add(part)
    session.flush()
    print(f"[seed] Inserted {len(pm_parts)} PM template spare parts.")


VENTILATOR_SCENARIO_NAME = "Ventilator Alternatives AHP"


def seed_ventilator_scenario(session) -> None:
    """
    Add the ventilator scenario profile used for the study if no profile has
    its name, so the Simulation page has something to load on a fresh
    database. AHP on crisis availability, total cost and three analyst
    scores; 12 alternatives = 38/41/45 ventilators × replacement every
    7/9/12/15 years, running 24/7.
    """
    if session.query(ScenarioProfileModel).filter(ScenarioProfileModel.name == VENTILATOR_SCENARIO_NAME).first():
        print(f"[seed] Scenario profile '{VENTILATOR_SCENARIO_NAME}' already exists, left as is.")
        return

    # Analyst scores per replacement period: (obsolescence, staff, logistics)
    scores_by_period = {
        7:  (10,  7.5, 7.5),
        9:  (10,  10,  10),
        12: (7.5, 7.5, 10),
        15: (5,   5,   7.5),
    }
    alternatives = []
    for replacement_period, (clinical, staff, logistics) in scores_by_period.items():
        for machine_number in (38, 41, 45):
            alternatives.append({
                "name": f"Alt-{len(alternatives) + 1}",
                "machine_number": machine_number,
                "replacement_period": replacement_period,
                "scores": {
                    "crisis_availability": 44,
                    "total_cost": 0,
                    "staff_satisfaction": staff,
                    "clinical_features": clinical,
                    "logistics_procurement": logistics,
                },
            })

    config = {
        "method": "AHP",
        "simulation": {
            "machine_type": "ventilator",
            "session_days": [0, 1, 2, 3, 4, 5, 6],
            "shift_durations": [24],
        },
        "criteria": [
            {"attribute_name": "crisis_availability", "name": "Available Machines — Crisis", "input_type": "threshold_int", "minimize": False},
            {"attribute_name": "total_cost", "name": "Total Cost", "input_type": "computed", "minimize": True},
            {"attribute_name": "staff_satisfaction", "name": "Staff Satisfaction", "input_type": "qualitative", "minimize": False},
            {"attribute_name": "clinical_features", "name": "Sensitivity to Obsolescence", "input_type": "qualitative", "minimize": False},
            {"attribute_name": "logistics_procurement", "name": "Easiness of Logistics & Procurement", "input_type": "qualitative", "minimize": False},
        ],
        "alternatives": alternatives,
        # Saaty judgements above the diagonal, row by row, in criteria order
        "pairwise_upper_triangle": [3, 5, 7, 9, 3, 5, 7, 3, 5, 3],
    }
    session.add(ScenarioProfileModel(name=VENTILATOR_SCENARIO_NAME, config=config))
    session.flush()
    print(f"[seed] Inserted scenario profile '{VENTILATOR_SCENARIO_NAME}' with {len(alternatives)} alternatives.")


def truncate_all(session):
    """Empty the fleet and result tables, children before parents."""
    from sqlalchemy import text
    from db.models import AlternativeModel, SimulationModel, EventModel, DecisionModel, CriteriaModel
    from db.models.simulation_output import decision_alternative_table, decision_criteria_table
    # A decision points to its best alternative, so clear that link before deleting either
    session.execute(text("UPDATE decision SET best_alternative_id = NULL"))
    session.execute(decision_alternative_table.delete())
    session.execute(decision_criteria_table.delete())
    session.query(EventModel).delete()
    session.query(SimulationModel).delete()
    session.query(AlternativeModel).delete()
    session.query(CriteriaModel).delete()
    session.query(DecisionModel).delete()
    session.query(PMCycleYearPartModel).delete()
    session.query(PMCycleYearModel).delete()
    session.query(SparePartModel).delete()
    session.query(MachineModel).delete()
    session.query(PreventiveMaintenanceModel).delete()
    session.query(MaintenanceCostDataModel).delete()
    session.flush()
    print("[seed] All tables truncated.")


def main():
    print("[seed] Starting database seed...")
    ensure_postgres_ready()

    SQLModel.metadata.create_all(get_engine())
    print("[seed] Tables created (or already exist).")

    with get_session() as session:
        truncate_all(session)
        seed_machine_types(session)
        cost_profiles = seed_cost_data(session)
        ventilator_pm = seed_pm_program(session)
        dialysis_pm = seed_pm_program_dialysis(session)
        seed_pm_parts(session, cost_profiles)
        seed_machines(session, cost_profiles, ventilator_pm, dialysis_pm)
        seed_ventilator_scenario(session)

    print("[seed] Done. Database is ready.")


if __name__ == "__main__":
    main()
