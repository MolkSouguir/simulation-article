"""
db/models/simulation_run.py

One saved call of POST /api/simulation/run, so past runs can be listed on the
History page and reopened exactly as they were shown.

request is what was sent (inputs, criteria, weights, settings), so the
Simulation page can fill its form again. result is everything that came back
(ranking, matrices, statistics, bootstrap, cost variation, parameter table).
chart_events holds, per alternative, the compact events of its first
replication, so the timeline and availability charts of any alternative can be
drawn again (see visualization.timeline.event_records). Older runs don't have
it, and their result still carries the charts of one alternative.

The summary columns repeat a few of those values so the History list never
has to load the large request and result.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB


class SimulationRunSummary(SQLModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    method: str
    machine_type: str
    alternative_count: int
    simulation_number: int
    period: int
    seed: int
    best_alternative: Optional[str] = None


class SimulationRunModel(SQLModel, table=True):
    __tablename__ = "simulation_run"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    method: str
    machine_type: str
    alternative_count: int
    simulation_number: int
    period: int
    seed: int
    best_alternative: Optional[str] = None
    request: Any = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    result: Any = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    chart_events: Any = Field(default=None, sa_column=Column(JSONB, nullable=True))


class SimulationRunUpdate(SQLModel):
    name: Optional[str] = None


class SimulationRunRead(SimulationRunSummary):
    request: Any
    result: Any
