"""
api/main.py

The FastAPI app. Start it with:
    uvicorn api.main:app --reload

Each router below covers one part of the app (machines, spare parts, cost
profiles, PM schedules, simulation, saved runs, tools, scenario profiles,
machine types).
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel
from sqlalchemy import text

from api.routers import machines, spare_parts, cost_profiles, preventive_maintenance, pm_cycle_years, simulation, simulation_runs, tools, scenario_profiles, machine_types
from db.session import get_engine, get_session


def _run_migrations():
    """
    Create any missing tables. Older databases stored machine.machine_type as
    a PostgreSQL enum. It is turned into plain text so new types can be added.
    simulation_run.chart_events is added if the table predates it.
    """
    engine = get_engine()
    SQLModel.metadata.create_all(engine)

    with engine.connect() as connection:
        result = connection.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'machine' AND column_name = 'machine_type'"
        )).fetchone()
        if result and result[0] == "USER-DEFINED":
            connection.execute(text(
                "ALTER TABLE machine ALTER COLUMN machine_type TYPE VARCHAR "
                "USING machine_type::text"
            ))
            connection.commit()

        # Added after the History page shipped, create_all doesn't add columns
        connection.execute(text(
            "ALTER TABLE simulation_run ADD COLUMN IF NOT EXISTS chart_events JSONB"
        ))
        connection.commit()

    # Default machine types on an empty table
    with get_session() as session:
        from db.models.machine_type import MachineTypeModel
        if session.query(MachineTypeModel).count() == 0:
            session.add_all([
                MachineTypeModel(name="ventilator"),
                MachineTypeModel(name="dialysis"),
            ])


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_migrations()
    yield


app = FastAPI(title="SimulationApp API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5176"],  # SvelteKit dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],   # so downloads keep the file name the API gives them
)

app.include_router(machine_types.router, prefix="/api/machine-types", tags=["machine-types"])
app.include_router(machines.router, prefix="/api/machines", tags=["machines"])
app.include_router(spare_parts.router, prefix="/api/spare-parts", tags=["spare-parts"])
app.include_router(cost_profiles.router, prefix="/api/cost-profiles", tags=["cost-profiles"])
app.include_router(preventive_maintenance.router, prefix="/api/preventive-maintenance", tags=["preventive-maintenance"])
app.include_router(
    pm_cycle_years.router,
    prefix="/api/preventive-maintenance/{pm_id}/cycle-years",
    tags=["pm-cycle-years"],
)


app.include_router(simulation.router, prefix="/api/simulation", tags=["simulation"])
app.include_router(simulation_runs.router, prefix="/api/simulation-runs", tags=["simulation-runs"])
app.include_router(tools.router, prefix="/api/tools", tags=["tools"])
app.include_router(scenario_profiles.router, prefix="/api/scenario-profiles", tags=["scenario-profiles"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
