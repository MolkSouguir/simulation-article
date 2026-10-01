"""
db/models/machine.py

Machine table, its API schemas, and the PM scheduling of a machine.
"""
import uuid
from math import ceil
from datetime import date
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship

from db.models.enums import MachineStatusEnum, MaintenanceItemType
from db.models.mixin import MaintenanceItemMixin
from db.models.maintenance_cost_data import MaintenanceCostDataModel
from db.models.preventive_maintenance import PreventiveMaintenanceModel, PMCycleYearModel


class MachineBase(SQLModel):
    name: str
    code: str
    machine_type: str = Field(foreign_key="machine_type.name")
    purchase_year: int
    purchase_cost: float
    status: MachineStatusEnum
    eta: float
    beta: float
    maintenance_cost_data_id: Optional[uuid.UUID] = Field(default=None, foreign_key="maintenance_cost_data.id")
    preventive_maintenance_id: Optional[uuid.UUID] = Field(default=None, foreign_key="preventive_maintenance.id")


class MachineModel(MaintenanceItemMixin, MachineBase, table=True):
    __tablename__ = "machine"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True)

    maintenance_cost_data: Optional[MaintenanceCostDataModel] = Relationship(back_populates="machines")
    preventive_maintenance: Optional[PreventiveMaintenanceModel] = Relationship(back_populates="machines")
    spare_parts: list["SparePartModel"] = Relationship(  # type: ignore[name-defined]
        back_populates="machine",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    @property
    def maintenance_item_type(self) -> MaintenanceItemType:
        return MaintenanceItemType.MACHINE

    # PM scheduling

    def get_pm_year(self, years: int = 0) -> Optional[PMCycleYearModel]:
        """The PM cycle year that applies `years` from now (None if no PM is due)."""
        schedule = self.preventive_maintenance
        if schedule is None or not schedule.preventive_maintenance_cycle_years:
            return None

        age = self.age + years
        interval = schedule.years_interval
        years_in_cycle = schedule.maintenance_cycle

        if age <= 0:
            return None

        pm_number = ceil(age / interval)
        year_index = (pm_number - 1) % years_in_cycle
        return schedule.preventive_maintenance_cycle_years[year_index]

    def calculate_pm_years(
        self,
        period: float,
        years_of_replacement_list: list[float] | None = None,
    ) -> list[float]:
        """
        Years from now at which a PM happens within `period`. A replacement
        restarts the machine's age, and no PM is done in a replacement year.
        """
        schedule = self.preventive_maintenance
        if schedule is None:
            return []

        pm_interval = schedule.years_interval
        if pm_interval <= 0:
            return []

        replacement_years = sorted(years_of_replacement_list) if years_of_replacement_list else []
        pm_times: list[float] = []
        current_age = self.age
        time_from_now = 0.0

        while time_from_now < period:
            next_pm_age = ceil((current_age + 0.001) / pm_interval) * pm_interval
            time_until_pm = next_pm_age - current_age
            next_pm_time = time_from_now + time_until_pm

            next_replacement = next(
                (replacement_year for replacement_year in replacement_years if replacement_year > time_from_now + 0.001),
                None,
            )

            if next_replacement is not None and next_replacement < next_pm_time:
                time_from_now = next_replacement
                current_age = 0
            else:
                if next_pm_time <= period:
                    is_replacement_year = any(
                        abs(next_pm_time - replacement_year) < 0.01 for replacement_year in replacement_years
                    )
                    if not is_replacement_year:
                        pm_times.append(next_pm_time)
                    time_from_now = next_pm_time
                    current_age = next_pm_age
                else:
                    break

        return pm_times


class MachineCreate(MachineBase):
    pass


class MachineUpdate(SQLModel):
    name: Optional[str] = None
    code: Optional[str] = None
    machine_type: Optional[str] = None
    purchase_year: Optional[int] = None
    purchase_cost: Optional[float] = None
    status: Optional[MachineStatusEnum] = None
    eta: Optional[float] = None
    beta: Optional[float] = None
    maintenance_cost_data_id: Optional[uuid.UUID] = None
    preventive_maintenance_id: Optional[uuid.UUID] = None


class SparePartSummary(SQLModel):
    id: uuid.UUID
    name: str
    code: str


class MachineRead(MachineBase):
    id: uuid.UUID
    spare_parts: list[SparePartSummary] = []


# spare_part.py imports MachineModel, so this import has to come after the
# class definition (the relationship above uses a string forward reference).
from db.models.spare_part import SparePartModel  # noqa: E402
