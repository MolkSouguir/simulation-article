"""
db/models/maintenance_cost_data.py

Cost profile (labour rate and repair hours): database table and API schemas.
"""
import uuid
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
from db.models.mixin import FastCopyMixin

if TYPE_CHECKING:
    from db.models.machine import MachineModel
    from db.models.spare_part import SparePartModel


class MaintenanceCostDataBase(SQLModel):
    name: str
    hourly_labor_cost: float
    corrective_maintenance_hours: float
    corrective_maintenance_additional_downtime_hours: float = Field(default=0.0)
    preventive_maintenance_hours: float


class MaintenanceCostDataModel(FastCopyMixin, MaintenanceCostDataBase, table=True):
    __tablename__ = "maintenance_cost_data"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    machines: list["MachineModel"] = Relationship(back_populates="maintenance_cost_data")
    spare_parts: list["SparePartModel"] = Relationship(back_populates="maintenance_cost_data")


class MaintenanceCostDataCreate(MaintenanceCostDataBase):
    pass


class MaintenanceCostDataUpdate(SQLModel):
    name: Optional[str] = None
    hourly_labor_cost: Optional[float] = None
    corrective_maintenance_hours: Optional[float] = None
    corrective_maintenance_additional_downtime_hours: Optional[float] = None
    preventive_maintenance_hours: Optional[float] = None


class MaintenanceCostDataRead(MaintenanceCostDataBase):
    id: uuid.UUID
