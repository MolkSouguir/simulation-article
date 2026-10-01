"""
db/models/spare_part.py

Spare part table, its API schemas, and the years in which PM replaces the part.
"""
import uuid
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

from db.models.enums import SparePartTypeEnum, SparePartStatusEnum, MaintenanceItemType
from db.models.mixin import MaintenanceItemMixin
from db.models.maintenance_cost_data import MaintenanceCostDataModel

if TYPE_CHECKING:
    from db.models.machine import MachineModel


class SparePartBase(SQLModel):
    name: str
    code: str
    spare_part_type: SparePartTypeEnum
    purchase_year: int
    purchase_cost: float
    status: SparePartStatusEnum
    eta: float
    beta: float
    machine_id: Optional[uuid.UUID] = Field(default=None, foreign_key="machine.id")
    maintenance_cost_data_id: Optional[uuid.UUID] = Field(default=None, foreign_key="maintenance_cost_data.id")


class SparePartModel(MaintenanceItemMixin, SparePartBase, table=True):
    __tablename__ = "spare_part"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    machine: Optional["MachineModel"] = Relationship(back_populates="spare_parts")
    maintenance_cost_data: Optional[MaintenanceCostDataModel] = Relationship(back_populates="spare_parts")

    @property
    def maintenance_item_type(self) -> MaintenanceItemType:
        return MaintenanceItemType.SPARE_PART

    @property
    def part_type(self) -> SparePartTypeEnum:
        """Same as spare_part_type. simulation.py looks parts up by this name."""
        return self.spare_part_type

    # PM replacement schedule

    def calculate_part_preplacement_years_indexes(self) -> list[int]:
        """Positions (from 0) of the PM cycle years that replace this type of part."""
        machine = self.machine
        if machine is None or machine.preventive_maintenance is None:
            return []

        matching_indexes: list[int] = []
        cycle_years = machine.preventive_maintenance.preventive_maintenance_cycle_years
        for cycle_index, cycle_year in enumerate(cycle_years):
            if any(
                pm_part.spare_part_type == self.spare_part_type
                for pm_part in cycle_year.preventive_maintenance_parts
            ):
                matching_indexes.append(cycle_index)
        return matching_indexes

    def get_replacement_years_in_period(self, period_years: int) -> list[int]:
        """Years from now in which PM replaces this part, within `period_years`."""
        machine = self.machine
        if machine is None or machine.preventive_maintenance is None:
            return []

        schedule = machine.preventive_maintenance
        years_interval = schedule.years_interval
        num_cycles = schedule.maintenance_cycle
        current_age = machine.age

        if num_cycles == 0 or years_interval == 0:
            return []

        part_cycle_indexes = self.calculate_part_preplacement_years_indexes()
        if not part_cycle_indexes:
            return []

        replacement_years: list[int] = []
        next_pm_absolute = ((current_age // years_interval) + 1) * years_interval
        end_absolute = current_age + period_years

        for absolute_year in range(next_pm_absolute, end_absolute + 1, years_interval):
            pm_number = absolute_year // years_interval
            cycle_index = (pm_number - 1) % num_cycles
            if cycle_index in part_cycle_indexes:
                replacement_years.append(absolute_year - current_age)

        return replacement_years


class SparePartCreate(SparePartBase):
    pass


class SparePartUpdate(SQLModel):
    name: Optional[str] = None
    code: Optional[str] = None
    spare_part_type: Optional[SparePartTypeEnum] = None
    purchase_year: Optional[int] = None
    purchase_cost: Optional[float] = None
    status: Optional[SparePartStatusEnum] = None
    eta: Optional[float] = None
    beta: Optional[float] = None
    machine_id: Optional[uuid.UUID] = None
    maintenance_cost_data_id: Optional[uuid.UUID] = None


class SparePartRead(SparePartBase):
    id: uuid.UUID
