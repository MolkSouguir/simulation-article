"""
maintenance_item_alternative.py

Replacement and PM years of one machine or part under one Alternative,
computed once before the simulation runs.
"""
from __future__ import annotations
from typing import List, TYPE_CHECKING, cast
from datetime import date
from db.models import MaintenanceItemType

if TYPE_CHECKING:
    from db.models import MachineModel, SparePartModel
    from classes.alternative import Alternative


class MaintenanceItemAlternative:
    def __init__(self, maintenance_item, alternative: "Alternative", pm_stagger_days: int = 0):
        self.replacement_period = alternative.replacement_period
        self.period = alternative.period
        self.maintenance_item = maintenance_item
        self.alternative = alternative
        self.pm_stagger_days = pm_stagger_days
        self.years_of_replacement_list = self.calculate_years_of_replacement_list()
        self.years_of_pm_list = self.calculate_years_of_pm()

    def calculate_years_of_pm(self) -> List[float]:
        if self.maintenance_item.maintenance_item_type == MaintenanceItemType.MACHINE:
            machine = cast("MachineModel", self.maintenance_item)
            pm_years = machine.calculate_pm_years(
                period=self.period,
                years_of_replacement_list=self.years_of_replacement_list,
            )
            pm_offset_years = self.pm_stagger_days / 365.0
            return [year - pm_offset_years for year in pm_years]
        return []

    def calculate_years_of_replacement_list(self) -> List[float]:
        if self.maintenance_item.maintenance_item_type == MaintenanceItemType.MACHINE:
            import database
            this_year = database.base_year
            years_of_replacement: List[float] = []
            machine_age = this_year - self.maintenance_item.purchase_year
            replacement_period = self.replacement_period
            period = self.period

            if machine_age < replacement_period:
                first_replacement = replacement_period - machine_age
                years_of_replacement.append(first_replacement)
                rest_replacements = (period - first_replacement) // replacement_period
                for _ in range(rest_replacements):
                    first_replacement += replacement_period
                    years_of_replacement.append(first_replacement)
            else:
                first_replacement = 0
                years_of_replacement.append(first_replacement)
                rest_replacements = (period - first_replacement) // replacement_period
                for _ in range(rest_replacements):
                    first_replacement += replacement_period
                    years_of_replacement.append(first_replacement)

            return years_of_replacement

        elif self.maintenance_item.maintenance_item_type == MaintenanceItemType.SPARE_PART:
            spare_part = cast("SparePartModel", self.maintenance_item)
            part_years = spare_part.get_replacement_years_in_period(self.period)
            return [float(year) for year in part_years]

        return []

    def to_dict(self):
        return {
            "maintenance_item": self.maintenance_item.name + self.maintenance_item.code,
            "alternative": self.alternative,
            "replacement_period": self.replacement_period,
            "period": self.period,
            "years_of_replacement_list": self.years_of_replacement_list,
        }

    def __repr__(self):
        return f"MachineAlternative: {self.to_dict()}"
