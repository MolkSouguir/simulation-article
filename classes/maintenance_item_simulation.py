"""
maintenance_item_simulation.py

State of one machine or spare part during a single simulation run.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, List, cast
from classes.event_type import EventType
from db.models import MachineStatusEnum, MachineModel
from functions.helper_functions import weibull_residual_life, ceil_from_list, ShiftSchedule
from classes.event import Event

if TYPE_CHECKING:
    from classes.simulation import Simulation
    from db.models import SparePartModel


class MaintenanceItemSimulation:
    def __init__(self, maintenance_item, simulation: "Simulation"):
        self.runtime: float = 0
        self.wear_age: float = 0
        self.eta: float = maintenance_item.eta
        self.beta: float = maintenance_item.beta
        self.maintenance_item = maintenance_item
        self.maintenance_item_parent: "MaintenanceItemSimulation | None" = None
        self.simulation = simulation
        self.events: List[Event] = []
        self.upcoming_events: List[Event] = []

        pm_stagger_days = getattr(maintenance_item, "pm_stagger_index", 0)
        item_alternative = self.maintenance_item.get_maintenance_item_alternative(
            self.simulation.alternative, pm_stagger_days=pm_stagger_days
        )
        self.years_of_replacement_list: list = item_alternative.years_of_replacement_list if item_alternative else []
        self.years_of_pm_list: list = item_alternative.years_of_pm_list if item_alternative else []

        self.completed_replacement_years: set = set()
        self.completed_pm_years: set = set()

        # Operating-hours clock of the machine. A machine keeps the same shift
        # for the whole run, so the schedule is built once here. Only machines
        # get a shift_slot (in Simulation.__init__), parts use their machine's.
        self.shift_schedule: "ShiftSchedule | None" = None
        shift_slot = getattr(maintenance_item, "shift_slot", None)
        if shift_slot is not None:
            alternative = self.simulation.alternative
            shift_hours = alternative.shift_durations[shift_slot % len(alternative.shift_durations)]
            self.shift_schedule = ShiftSchedule(shift_hours, alternative.session_days)

    def add_parent(self, maintenance_item_simulation: "MaintenanceItemSimulation"):
        self.maintenance_item_parent = maintenance_item_simulation

    @property
    def effective_shift_schedule(self) -> "ShiftSchedule":
        """Schedule that drives this item's wear: its own for a machine, the
        parent machine's for a part (a part only wears while its machine runs)."""
        owner = self if self.maintenance_item_parent is None else self.maintenance_item_parent
        schedule = owner.shift_schedule
        assert schedule is not None, "machine-level MaintenanceItemSimulation always has a shift_schedule"
        return schedule

    def mark_event_completed(self, event: Event):
        if event.event_type == EventType.PREVENTIVE_MAINTENANCE:
            self.completed_pm_years.add(event.start_time)
        elif event.event_type == EventType.PURCHASE_REPLACEMENT:
            self.completed_replacement_years.add(event.start_time)

    def get_pending_events(self) -> List[Event]:
        pending: List[Event] = []

        # Events are not marked as completed here. The handlers do that
        # (mark_event_completed), so pending events are still sorted together
        # with the other machines' events and the log stays chronological.
        for year in self.years_of_replacement_list:
            if year not in self.completed_replacement_years and year <= self.runtime:
                purchase_cost = self.maintenance_item.unit_cost(year)
                pending.append(Event(
                    start_time=year,
                    end_time=year + 0.001,
                    event_type=EventType.PURCHASE_REPLACEMENT,
                    maintenance_item=self.maintenance_item,
                    cost=purchase_cost,
                ))

        for year in self.years_of_pm_list:
            if year not in self.completed_pm_years and year <= self.runtime:
                pending.append(Event(
                    start_time=year,
                    end_time=year,
                    event_type=EventType.PREVENTIVE_MAINTENANCE,
                    maintenance_item=self.maintenance_item,
                ))

        return pending

    def get_next_event(self) -> Event | None:
        period = self.simulation.alternative.period

        if self.maintenance_item_parent is None:
            # Machine
            current_year = self.runtime
            next_replacement = ceil_from_list(self.years_of_replacement_list, current_year)
            next_pm = ceil_from_list(self.years_of_pm_list, current_year)

            candidates: List[Event] = []

            # Events at exactly t == period fall outside the horizon (see
            # Simulation._best_event_for).
            for upcoming_event in self.upcoming_events:
                if upcoming_event.start_time < period:
                    candidates.append(upcoming_event)

            if not candidates and self.upcoming_events:
                for upcoming_event in self.upcoming_events:
                    upcoming_event.remove_from_machine_events(maintenance_item_simulation=self, upcoming=True)
                    upcoming_event.remove_from_simulation_events(simulation=self.simulation, upcoming=True)

            if next_replacement is not None and next_replacement not in self.completed_replacement_years:
                purchase_cost = self.maintenance_item.unit_cost(next_replacement)
                candidates.append(Event(
                    start_time=next_replacement,
                    end_time=next_replacement + 0.001,
                    event_type=EventType.PURCHASE_REPLACEMENT,
                    maintenance_item=self.maintenance_item,
                    cost=purchase_cost,
                ))

            if next_pm is not None and next_pm not in self.completed_pm_years:
                candidates.append(Event(
                    start_time=next_pm,
                    end_time=next_pm,
                    event_type=EventType.PREVENTIVE_MAINTENANCE,
                    maintenance_item=self.maintenance_item,
                ))

            # Machine-level failure, only if beta and eta are set. The Weibull
            # draw is in operating time (wear_age) and is then converted to a
            # calendar date with the shift schedule. For a 24/7 schedule the
            # two are the same.
            machine = cast(MachineModel, self.maintenance_item)
            if self.beta > 0 and self.eta > 0 and machine.status == MachineStatusEnum.ACTIVE:
                next_failure_wear = weibull_residual_life(
                    beta=self.beta, eta=self.eta, current_age=self.wear_age
                )
                calendar_offset = self.effective_shift_schedule.to_calendar_offset(next_failure_wear)
                if self.runtime + calendar_offset < period:
                    candidates.append(Event(
                        start_time=self.runtime + calendar_offset,
                        end_time=self.runtime + calendar_offset,
                        event_type=EventType.FAILURE,
                        maintenance_item=self.maintenance_item,
                    ))

            return min(candidates, key=lambda candidate: candidate.start_time, default=None)

        else:
            # Spare part. It only wears while its machine is running, so it
            # uses the machine's shift schedule.
            parent = self.maintenance_item_parent
            machine = cast("MachineModel", parent.maintenance_item)
            current_year = parent.runtime
            next_failure_wear = weibull_residual_life(beta=self.beta, eta=self.eta, current_age=self.wear_age)
            calendar_offset = self.effective_shift_schedule.to_calendar_offset(next_failure_wear)

            if current_year + calendar_offset < period and machine.status == MachineStatusEnum.ACTIVE:
                return Event(
                    start_time=current_year + calendar_offset,
                    end_time=current_year + calendar_offset,
                    event_type=EventType.FAILURE,
                    maintenance_item=self.maintenance_item,
                )
            return None
