"""
db/models/mixin.py

Simulation behaviour shared by MachineModel and SparePartModel.

load_config() detaches every loaded object from the database session
(make_transient), so during a run these are plain Python objects. The mixin
adds what the simulation needs on top of the database columns.
"""
from __future__ import annotations
import copy
import enum
import uuid
import weakref
from datetime import date
from typing import TYPE_CHECKING

# Immutable values: the copy can simply point to the same object.
_IMMUTABLE_TYPES = (int, float, str, bool, bytes, type(None), uuid.UUID, enum.Enum)


class FastCopyMixin:
    """
    Faster deepcopy for SQLModel objects. The default path goes through
    SQLAlchemy/pydantic's __reduce_ex__, which was the bottleneck of the
    simulation loop. Used by every model that gets copied for a run.
    """

    def __deepcopy__(self, memo: dict):
        model_class = type(self)
        new_obj = object.__new__(model_class)
        memo[id(self)] = new_obj

        # Pydantic keeps these outside __dict__, so copy them first.
        for pydantic_slot in ("__pydantic_fields_set__", "__pydantic_extra__", "__pydantic_private__"):
            try:
                slot_value = object.__getattribute__(self, pydantic_slot)
                object.__setattr__(new_obj, pydantic_slot, copy.copy(slot_value))
            except AttributeError:
                pass

        # A fresh SQLAlchemy instance state, otherwise setting attributes fails.
        from sqlalchemy.orm.instrumentation import manager_of_class
        manager = manager_of_class(model_class)
        if manager is not None:
            manager.setup_instance(new_obj)
            new_obj._sa_instance_state.obj = weakref.ref(new_obj)  # type: ignore[attr-defined]

        # Copy the data attributes straight into __dict__.
        for key, value in self.__dict__.items():
            if key == "_sa_instance_state":
                continue
            if isinstance(value, _IMMUTABLE_TYPES):
                new_obj.__dict__[key] = value
            elif isinstance(value, list):
                # Copied as a plain list, without SQLAlchemy's InstrumentedList.
                new_obj.__dict__[key] = [
                    copy.deepcopy(item, memo) if not isinstance(item, _IMMUTABLE_TYPES) else item
                    for item in value
                ]
            else:
                new_obj.__dict__[key] = copy.deepcopy(value, memo)

        return new_obj


class MaintenanceItemMixin(FastCopyMixin):
    """
    init_simulation_state() adds two attributes that are not database columns:
    maintenance_item_alternatives (the schedule of this item per alternative,
    cached) and maintenance_item_simulations (its state in each run).
    """
    if TYPE_CHECKING:
        maintenance_item_alternatives: list
        maintenance_item_simulations: list
        _simulation_lookup: dict

    def init_simulation_state(self) -> None:
        """Call once after make_transient(), and again on every deepcopy."""
        object.__setattr__(self, "maintenance_item_alternatives", [])
        object.__setattr__(self, "maintenance_item_simulations", [])
        object.__setattr__(self, "_simulation_lookup", {})

    @property
    def age(self) -> int:
        import database
        return database.base_year - self.purchase_year  # type: ignore[attr-defined]

    def unit_cost(self, year: float = 0) -> float:
        """Purchase price, with inflation for machines (parts keep their price)."""
        import database
        from db.models.machine import MachineModel
        purchase_cost: float = self.purchase_cost  # type: ignore[attr-defined]
        if isinstance(self, MachineModel):
            year_difference = database.base_year - self.purchase_year + year  # type: ignore[attr-defined]
            return round(purchase_cost * (database.inflation_rate + 1) ** year_difference, 2)
        return round(purchase_cost, 2)

    def create_maintenance_item_alternative(self, alternative, pm_stagger_days: int = 0):
        from classes.maintenance_item_alternative import MaintenanceItemAlternative
        item_alternative = MaintenanceItemAlternative(
            maintenance_item=self,
            alternative=alternative,
            pm_stagger_days=pm_stagger_days,
        )
        self.maintenance_item_alternatives.append(item_alternative)
        return item_alternative

    def get_maintenance_item_alternative(self, alternative, pm_stagger_days: int = 0):
        from functions.helper_functions import find_obj_by_attr
        # Only schedules without a PM offset are shared, so only those are cached.
        if pm_stagger_days == 0:
            existing = find_obj_by_attr(self.maintenance_item_alternatives, "alternative", alternative)
            if existing is None:
                existing = self.create_maintenance_item_alternative(alternative, pm_stagger_days)
        else:
            existing = self.create_maintenance_item_alternative(alternative, pm_stagger_days)
        return existing

    def create_maintenance_item_simulation(self, simulation):
        from classes.maintenance_item_simulation import MaintenanceItemSimulation
        item_simulation = MaintenanceItemSimulation(maintenance_item=self, simulation=simulation)
        self.maintenance_item_simulations.append(item_simulation)
        self._simulation_lookup[id(simulation)] = item_simulation
        simulation.maintenance_item_simulations.append(item_simulation)
        return item_simulation

    def get_maintenance_item_simulation(self, simulation):
        item_simulation = self._simulation_lookup.get(id(simulation))
        if item_simulation is None:
            item_simulation = self.create_maintenance_item_simulation(simulation)
        return item_simulation
