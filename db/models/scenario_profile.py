"""
db/models/scenario_profile.py

A saved scenario: criteria, alternatives and settings under a name, so it can
be loaded again on the Simulation page.

What config looks like:
{
  "criteria": [
    { "attribute_name": str, "name": str, "input_type": str, "minimize": bool }
  ],
  "alternatives": [
    { "name": str, "machine_number": int, "replacement_period": int, "scores": { attr: float } }
  ]
}
"""
import uuid
from typing import Optional, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB


class ScenarioProfileModel(SQLModel, table=True):
    __tablename__ = "scenario_profile"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    config: Any = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))


class ScenarioProfileCreate(SQLModel):
    name: str
    config: Any


class ScenarioProfileUpdate(SQLModel):
    name: Optional[str] = None
    config: Optional[Any] = None


class ScenarioProfileRead(SQLModel):
    id: uuid.UUID
    name: str
    config: Any
