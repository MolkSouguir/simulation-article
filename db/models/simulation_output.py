"""
db/models/simulation_output.py

Tables for simulation results (alternatives, runs, events, criteria, decisions).
There is no CRUD API for them, only db/persistence.py writes to them.
"""
import uuid
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from db.models.enums import EventTypeEnum, DecisionMethodTypeEnum

# Link tables for the many-to-many relations
decision_alternative_table = Table(
    "decision_alternative",
    SQLModel.metadata,
    Column("decision_id", PG_UUID(as_uuid=True), ForeignKey("decision.id"), primary_key=True),
    Column("alternative_id", PG_UUID(as_uuid=True), ForeignKey("alternative.id"), primary_key=True),
)

decision_criteria_table = Table(
    "decision_criteria",
    SQLModel.metadata,
    Column("decision_id", PG_UUID(as_uuid=True), ForeignKey("decision.id"), primary_key=True),
    Column("criteria_id", PG_UUID(as_uuid=True), ForeignKey("criteria.id"), primary_key=True),
)


class AlternativeModel(SQLModel, table=True):
    __tablename__ = "alternative"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    machine_number: int
    replacement_period: int
    period: int
    simulation_number: int
    normal_threshold: int
    crisis_threshold: int

    total_cost: Optional[float] = None
    purchase_cost: Optional[float] = None
    corrective_maintenance_cost: Optional[float] = None
    preventive_maintenance_cost: Optional[float] = None
    normal_availability: Optional[float] = None
    crisis_availability: Optional[float] = None

    clinical_features: Optional[float] = None
    staff_satisfaction: Optional[float] = None
    logistics_procurement: Optional[float] = None

    simulations: list["SimulationModel"] = Relationship(
        back_populates="alternative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    decisions: list["DecisionModel"] = Relationship(
        back_populates="alternatives",
        sa_relationship_kwargs={"secondary": decision_alternative_table},
    )


class SimulationModel(SQLModel, table=True):
    __tablename__ = "simulation"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    simulation_number: int
    purchase_cost: float = 0
    corrective_maintenance_cost: float = 0
    preventive_maintenance_cost: float = 0
    normal_availability: Optional[float] = None
    crisis_availability: Optional[float] = None

    alternative_id: uuid.UUID = Field(foreign_key="alternative.id")

    alternative: Optional[AlternativeModel] = Relationship(back_populates="simulations")
    events: list["EventModel"] = Relationship(
        back_populates="simulation",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class EventModel(SQLModel, table=True):
    __tablename__ = "event"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    event_type: EventTypeEnum
    start_time: float
    end_time: float
    duration: float = 0
    cost: float = 0
    description: Optional[str] = None
    maintenance_item_name: Optional[str] = None
    maintenance_item_code: Optional[str] = None

    simulation_id: uuid.UUID = Field(foreign_key="simulation.id")

    simulation: Optional[SimulationModel] = Relationship(back_populates="events")


class CriteriaModel(SQLModel, table=True):
    __tablename__ = "criteria"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    attribute_name: str
    rank: Optional[int] = None
    weight: Optional[float] = None
    minimize: bool = False

    decisions: list["DecisionModel"] = Relationship(
        back_populates="criteria",
        sa_relationship_kwargs={"secondary": decision_criteria_table},
    )


class DecisionModel(SQLModel, table=True):
    __tablename__ = "decision"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    method: DecisionMethodTypeEnum
    consistency_ratio: Optional[float] = None
    best_alternative_id: Optional[uuid.UUID] = Field(default=None, foreign_key="alternative.id")

    alternatives: list[AlternativeModel] = Relationship(
        back_populates="decisions",
        sa_relationship_kwargs={"secondary": decision_alternative_table},
    )
    criteria: list[CriteriaModel] = Relationship(
        back_populates="decisions",
        sa_relationship_kwargs={"secondary": decision_criteria_table},
    )
    best_alternative: Optional[AlternativeModel] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DecisionModel.best_alternative_id]"},
    )
