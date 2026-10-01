"""
db/models/preventive_maintenance.py

PM schedules, their cycle years and the parts replaced each cycle year:
database tables and API schemas.
"""
import uuid
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import UniqueConstraint

from db.models.enums import SparePartTypeEnum
from db.models.mixin import FastCopyMixin

if TYPE_CHECKING:
    from db.models.machine import MachineModel


class PreventiveMaintenanceBase(SQLModel):
    name: str
    years_interval: int


class PreventiveMaintenanceModel(FastCopyMixin, PreventiveMaintenanceBase, table=True):
    __tablename__ = "preventive_maintenance"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True)

    machines: list["MachineModel"] = Relationship(back_populates="preventive_maintenance")
    cycle_years: list["PMCycleYearModel"] = Relationship(
        back_populates="preventive_maintenance",
        sa_relationship_kwargs={"order_by": "PMCycleYearModel.order", "cascade": "all, delete-orphan"},
    )

    @property
    def maintenance_cycle(self) -> int:
        """Length of the full PM cycle in years: interval x number of cycle years."""
        return self.years_interval * len(self.cycle_years)

    @property
    def preventive_maintenance_cycle_years(self) -> list["PMCycleYearModel"]:
        """Same as cycle_years. The machine and spare part code use this name."""
        return self.cycle_years


# Parts replaced in a cycle year

class PMCycleYearPartModel(FastCopyMixin, SQLModel, table=True):
    __tablename__ = "pm_cycle_year_part"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    spare_part_type: SparePartTypeEnum
    pm_cycle_year_id: uuid.UUID = Field(foreign_key="pm_cycle_year.id")

    cycle_year: Optional["PMCycleYearModel"] = Relationship(back_populates="parts")


class PMCycleYearPartRead(SQLModel):
    id: uuid.UUID
    spare_part_type: SparePartTypeEnum


# Cycle years

class PMCycleYearBase(SQLModel):
    order: int
    preventive_maintenance_hours: float
    hourly_labor_cost: float
    pm_year_cost: float


class PMCycleYearModel(FastCopyMixin, PMCycleYearBase, table=True):
    __tablename__ = "pm_cycle_year"  # type: ignore
    __table_args__ = (
        UniqueConstraint("preventive_maintenance_id", "order", name="uq_pm_cycle_year_order"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    preventive_maintenance_id: uuid.UUID = Field(foreign_key="preventive_maintenance.id")

    preventive_maintenance: Optional[PreventiveMaintenanceModel] = Relationship(back_populates="cycle_years")
    parts: list[PMCycleYearPartModel] = Relationship(
        back_populates="cycle_year",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    @property
    def preventive_maintenance_parts(self) -> list[PMCycleYearPartModel]:
        """Same as parts. The simulation reads it to know which parts a PM replaces."""
        return self.parts


class PMCycleYearCreate(SQLModel):
    order: int
    preventive_maintenance_hours: float
    hourly_labor_cost: float
    pm_year_cost: float
    parts: list[SparePartTypeEnum] = []


class PMCycleYearUpdate(SQLModel):
    order: Optional[int] = None
    preventive_maintenance_hours: Optional[float] = None
    hourly_labor_cost: Optional[float] = None
    pm_year_cost: Optional[float] = None
    parts: Optional[list[SparePartTypeEnum]] = None


class PMCycleYearRead(PMCycleYearBase):
    id: uuid.UUID
    parts: list[PMCycleYearPartRead] = []


class PreventiveMaintenanceCreate(PreventiveMaintenanceBase):
    cycle_years: list[PMCycleYearCreate] = []


class PreventiveMaintenanceUpdate(SQLModel):
    name: Optional[str] = None
    years_interval: Optional[int] = None


class PreventiveMaintenanceRead(PreventiveMaintenanceBase):
    id: uuid.UUID
    cycle_years: list[PMCycleYearRead] = []
