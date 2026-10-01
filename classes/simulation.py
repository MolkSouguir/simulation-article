"""
simulation.py

One Monte Carlo run of the fleet maintenance simulation (discrete events).
"""
from __future__ import annotations
from typing import List, TYPE_CHECKING, cast
from functions.helper_functions import find_all_by_attr, find_obj_by_attr, calculate_session_availability, calculate_resilience_metrics, ceil_from_list
from classes.event_type import EventType
from db.models import MachineStatusEnum, MachineModel, SparePartModel
from database import db_machines, simulations
from operator import attrgetter
from db.models import MachineTypeEnum
import copy
import heapq
import weakref
from sqlalchemy.orm.base import instance_state as sa_instance_state
from classes.event import Event

if TYPE_CHECKING:
    from classes.maintenance_item_simulation import MaintenanceItemSimulation
    from classes.alternative import Alternative


class Simulation:
    def __init__(self, alternative: "Alternative", machine_number: int, normal_threshold: int, crisis_threshold: int, machine_type: MachineTypeEnum = MachineTypeEnum.VENTILATOR):
        self.simulation_number = len(alternative.simulations) + 1
        self.purchase_cost: float = 0
        self.corrective_maintenance_cost: float = 0
        self.preventive_maintenance_cost: float = 0
        self.alternative = alternative
        self.maintenance_item_simulations: List["MaintenanceItemSimulation"] = []
        self.events: List[Event] = []
        self.upcoming_events: List[Event] = []
        self.normal_availability: float = 0
        self.crisis_availability: float = 0
        self.resilience: dict[str, float] = {}

        period = alternative.period

        # Machines of the requested type, youngest first, copied for this run.
        typed_machines = [db_machine for db_machine in db_machines if db_machine.machine_type == machine_type]
        typed_machines.sort(key=attrgetter("age"))

        if machine_number > len(typed_machines):
            raise ValueError(
                f"Alternative requests {machine_number} machines of type '{machine_type}', "
                f"but only {len(typed_machines)} are loaded in the database. "
                f"Reduce machine_number or add more {machine_type} machines."
            )

        def _rewire_sa_state(model_instance) -> None:
            """After a deepcopy, SQLAlchemy's instance state still points (weakly)
            to the original object. Point it to the copy, otherwise writing an
            attribute fails once the original has been garbage collected."""
            state = sa_instance_state(model_instance)
            state.obj = weakref.ref(model_instance)
            state._strong_obj = None

        simulation_machines: List[MachineModel] = []
        for machine_index in range(machine_number):
            machine: MachineModel = copy.deepcopy(typed_machines[machine_index])
            _rewire_sa_state(machine)
            for part in machine.spare_parts:
                _rewire_sa_state(part)
            machine.status = MachineStatusEnum.ACTIVE if machine_index < normal_threshold else MachineStatusEnum.STANDBY
            object.__setattr__(machine, "pm_stagger_index", machine_index)
            object.__setattr__(machine, "shift_slot", machine_index % len(alternative.shift_durations))
            # The deepcopy carries over the original's lists, so reset the run state.
            machine.init_simulation_state()
            for part in machine.spare_parts:
                part.init_simulation_state()
            simulation_machines.append(machine)

        # Event queue
        #
        # A heap holds at most one live entry per machine:
        #   (start_time, push_order, event, machine_simulation, machine_id, version)
        # push_order breaks ties so two Event objects are never compared.
        # machine_id is id(machine), used to find the machine again.
        # version goes up every time a machine is rescheduled, and older entries of
        # that machine are skipped when they come out of the heap.
        #
        # After an event is handled, only the machines it affected are
        # rescheduled, so each Weibull failure time is drawn once.

        start_event = Event(
            start_time=0, end_time=0,
            event_type=EventType.START_OF_SIMULATION,
            maintenance_item=None,
        )
        self.events.append(start_event)

        # Other machines whose state a handler changed (a standby put into
        # service, a repair redirected). They get rescheduled after the event.
        self._machines_to_reschedule: set[int] = set()

        heap_versions: dict[int, int] = {id(machine): 0 for machine in simulation_machines}
        machine_by_id: dict[int, MachineModel] = {id(machine): machine for machine in simulation_machines}
        push_counter: list[int] = [0]   # a list so the nested function can update it
        event_heap: list = []

        def _best_event_for(machine: MachineModel, machine_simulation: "MaintenanceItemSimulation") -> Event | None:
            """Earliest upcoming event of this machine and its parts."""
            candidates: List[Event] = []

            # PMs and replacements that came due while the machine was on standby
            candidates.extend(machine_simulation.get_pending_events())

            # Next machine event: PM, replacement, or a planned end of repair
            next_machine_event = machine_simulation.get_next_event()
            if next_machine_event is not None:
                candidates.append(next_machine_event)

            # Next failure of each spare part (only drawn while the machine is active)
            if machine_simulation.runtime < period:
                for part in machine.spare_parts:
                    part_simulation = part.get_maintenance_item_simulation(simulation=self)
                    if part_simulation.maintenance_item_parent is None:
                        part_simulation.add_parent(machine_simulation)
                    part_event = part_simulation.get_next_event()
                    if part_event is not None:
                        candidates.append(part_event)

            if not candidates:
                return None
            best = min(candidates, key=lambda candidate: candidate.start_time)
            # The horizon is [0, period). An event at exactly t == period (for
            # example a replacement or PM falling on the last year) gives no
            # service inside the horizon, so it is neither handled nor costed.
            return best if best.start_time < period else None

        def _push(machine: MachineModel) -> None:
            """Work out the machine's next event and put it on the heap."""
            machine_simulation = machine.get_maintenance_item_simulation(simulation=self)
            if machine_simulation.runtime >= period:
                return
            best = _best_event_for(machine, machine_simulation)
            if best is None:
                machine_simulation.runtime = period
                return
            heap_versions[id(machine)] += 1
            push_counter[0] += 1
            heapq.heappush(
                event_heap,
                (best.start_time, push_counter[0], best, machine_simulation, id(machine), heap_versions[id(machine)])
            )

        # One starting entry per machine
        for machine in simulation_machines:
            _push(machine)

        while event_heap:
            _, _, event, machine_simulation, machine_id, version = heapq.heappop(event_heap)

            # Outdated entry: the machine was rescheduled after this was pushed
            if version != heap_versions[machine_id]:
                continue

            if machine_simulation.runtime >= period:
                continue

            if event.event_type == EventType.FAILURE:
                self.handle_failure(event, machine_simulation, simulation_machines)
            elif event.event_type == EventType.PURCHASE_REPLACEMENT:
                self.handle_purchase_replacement(event, machine_simulation)
            elif event.event_type == EventType.PREVENTIVE_MAINTENANCE:
                self.handle_preventive_maintenance(event, machine_simulation, simulation_machines)
            elif event.event_type == EventType.TO_SERVICE:
                self.handle_to_service(event, machine_simulation)
            elif event.event_type == EventType.END_OF_MAINTENANCE:
                self.handle_end_of_maintenance(event, machine_simulation)

            # The machine that had the event, plus any others the handler touched
            _push(machine_by_id[machine_id])
            for affected_machine_id in self._machines_to_reschedule:
                _push(machine_by_id[affected_machine_id])
            self._machines_to_reschedule.clear()

        # Only replication 1 is registered: the charts read "simulation-1", and
        # keeping the events of every replication here would hold on to all of
        # them (a few MB each) until the next alternative overwrites the keys.
        if self.simulation_number == 1:
            simulations["simulation-1"] = self.events

        self.normal_availability = calculate_session_availability(
            events=self.events, total_machines=machine_number, threshold=normal_threshold,
            period=period, session_days=alternative.session_days,
            shift_durations=alternative.shift_durations,
        )
        self.crisis_availability = calculate_session_availability(
            events=self.events, total_machines=machine_number, threshold=crisis_threshold,
            period=period, session_days=alternative.session_days,
            shift_durations=alternative.shift_durations,
        )
        self.resilience = calculate_resilience_metrics(
            events=self.events, total_machines=machine_number,
            threshold=crisis_threshold, period=period,
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _wear_elapsed(machine_simulation: "MaintenanceItemSimulation", elapsed: float) -> float:
        """Operating time (in years) a machine gained over `elapsed` calendar years."""
        return machine_simulation.effective_shift_schedule.wear_accrued(elapsed)

    def handle_failure(
        self,
        next_event: Event,
        machine_simulation: "MaintenanceItemSimulation",
        simulation_machines: List[MachineModel],
    ):
        if next_event.maintenance_item is None:
            return

        machine = cast(MachineModel, machine_simulation.maintenance_item)
        machine_parts = machine.spare_parts
        part_simulations = [part.get_maintenance_item_simulation(self) for part in machine_parts]

        cost_data = next_event.maintenance_item.maintenance_cost_data
        if cost_data is None:
            return

        labor_hours = cost_data.corrective_maintenance_hours
        downtime_hours = labor_hours + (cost_data.corrective_maintenance_additional_downtime_hours or 0.0)

        is_machine_failure = isinstance(next_event.maintenance_item, MachineModel)
        part_cost = 0.0 if is_machine_failure else next_event.maintenance_item.unit_cost()

        corrective_cost = (cost_data.hourly_labor_cost * labor_hours) + part_cost
        self.corrective_maintenance_cost += corrective_cost

        repair_end_time = next_event.start_time + (downtime_hours / 8760)

        # A repair can't run past the machine's next PM or replacement.
        next_scheduled: list[float] = []
        next_replacement = ceil_from_list(machine_simulation.years_of_replacement_list, next_event.start_time)
        if next_replacement is not None:
            next_scheduled.append(next_replacement)
        next_pm = ceil_from_list(machine_simulation.years_of_pm_list, next_event.start_time)
        if next_pm is not None:
            next_scheduled.append(next_pm)
        if next_scheduled:
            next_scheduled_time = min(next_scheduled)
            if repair_end_time > next_scheduled_time:
                repair_end_time = next_scheduled_time

        corrective_event = Event(
            start_time=next_event.start_time, end_time=repair_end_time,
            event_type=EventType.CORRECTIVE_MAINTENANCE,
            maintenance_item=next_event.maintenance_item, cost=corrective_cost,
        )
        end_of_maintenance_event = Event(
            start_time=repair_end_time, end_time=repair_end_time,
            event_type=EventType.END_OF_MAINTENANCE,
            maintenance_item=machine,
        )
        # Availability only looks at OUT_OF_SERVICE events.
        # CORRECTIVE_MAINTENANCE is just there for the cost. It is added here so
        # the downtime is counted even when replace_machine finds no standby
        # and no machine to redirect.
        out_of_service_event = Event(
            start_time=next_event.start_time, end_time=repair_end_time,
            event_type=EventType.OUT_OF_SERVICE,
            maintenance_item=next_event.maintenance_item,
        )

        next_event.add_to_simulation_events(self)
        corrective_event.add_to_simulation_events(self)
        out_of_service_event.add_to_simulation_events(self)
        end_of_maintenance_event.add_to_simulation_events(self, upcoming=True)
        next_event.add_to_machine_events(machine_simulation)
        corrective_event.add_to_machine_events(machine_simulation)
        out_of_service_event.add_to_machine_events(machine_simulation)
        end_of_maintenance_event.add_to_machine_events(machine_simulation, upcoming=True)

        machine.status = MachineStatusEnum.MAINTENANCE
        elapsed = next_event.start_time - machine_simulation.runtime
        wear_elapsed = self._wear_elapsed(machine_simulation, elapsed)
        machine_simulation.runtime = next_event.start_time
        machine_simulation.wear_age += wear_elapsed

        # The failed part starts from zero, the other parts keep ageing.
        for part_simulation in part_simulations:
            if part_simulation.maintenance_item != next_event.maintenance_item:
                part_simulation.runtime += elapsed
                part_simulation.wear_age += wear_elapsed
            else:
                part_simulation.runtime = 0
                part_simulation.wear_age = 0

        self.replace_machine(
            gap_start_time=next_event.start_time,
            machine=machine,
            machine_simulation=machine_simulation,
            simulation_machines=simulation_machines,
        )

    def replace_machine(
        self,
        gap_start_time: float,
        machine: MachineModel,
        machine_simulation: "MaintenanceItemSimulation",
        simulation_machines: List[MachineModel],
    ) -> bool:
        """
        Cover for `machine`, which goes out of service at `gap_start_time`
        (failure or PM).

        If a standby machine is free, it goes into service right away. If none
        is free but the fleet has a standby pool, the machine whose repair ends
        first comes straight into service instead of going back to standby,
        and its wait is recorded as OUT_OF_SERVICE.

        Returns False when nobody can cover the gap. Either way the caller has
        already recorded the machine's own downtime as OUT_OF_SERVICE.
        """
        no_standby_pool = self.alternative.normal_threshold >= self.alternative.machine_number

        machines_in_stock: List[MachineModel] = find_all_by_attr(
            simulation_machines, "status", MachineStatusEnum.STANDBY
        )
        if machines_in_stock:
            machine_to_replace = min(machines_in_stock, key=lambda standby_machine: standby_machine.purchase_year)
            to_service_event = Event(
                start_time=gap_start_time, end_time=gap_start_time,
                event_type=EventType.TO_SERVICE, maintenance_item=machine_to_replace,
            )
            replacement_simulation = machine_to_replace.get_maintenance_item_simulation(self)
            to_service_event.add_to_simulation_events(self)
            to_service_event.add_to_machine_events(replacement_simulation)
            machine_to_replace.status = MachineStatusEnum.ACTIVE
            # Only the calendar clock is moved to "now", the moment the gap
            # opens. The standby keeps its own wear_age: wear belongs to the
            # physical unit. (Not machine_simulation.runtime: during a PM that
            # is still the covered machine's previous event, which would date
            # the standby back and give its parts wear they never had.)
            replacement_simulation.runtime = max(replacement_simulation.runtime, gap_start_time)
            # It is active now, so its next event is a failure draw. Reschedule it.
            self._machines_to_reschedule.add(id(machine_to_replace))
            return True

        if no_standby_pool:
            # Without a pool the failed machine simply comes back when its repair ends.
            return False

        upcoming_repair_ends: List[Event] = find_all_by_attr(
            self.upcoming_events, "event_type", EventType.END_OF_MAINTENANCE
        )
        other_repair_ends = [repair_end for repair_end in upcoming_repair_ends if repair_end.maintenance_item != machine]

        if other_repair_ends:
            maintenance_event = min(other_repair_ends, key=lambda repair_end: repair_end.end_time)
        elif upcoming_repair_ends:
            maintenance_event = min(upcoming_repair_ends, key=lambda repair_end: repair_end.end_time)
        else:
            return False

        machine_to_replace = maintenance_event.maintenance_item
        if machine_to_replace is None:
            return False

        to_service_event = Event(
            start_time=maintenance_event.end_time, end_time=maintenance_event.end_time,
            event_type=EventType.TO_SERVICE, maintenance_item=machine_to_replace,
        )
        out_of_service_event = Event(
            start_time=gap_start_time, end_time=maintenance_event.end_time,
            event_type=EventType.OUT_OF_SERVICE, maintenance_item=machine_to_replace,
        )
        replacement_simulation = machine_to_replace.get_maintenance_item_simulation(self)
        out_of_service_event.add_to_simulation_events(self)
        out_of_service_event.add_to_machine_events(replacement_simulation)
        replacement_simulation.runtime = maintenance_event.end_time
        maintenance_event.remove_from_machine_events(replacement_simulation, upcoming=True)
        maintenance_event.remove_from_simulation_events(self, upcoming=True)
        to_service_event.add_to_simulation_events(self, upcoming=True)
        to_service_event.add_to_machine_events(replacement_simulation, upcoming=True)
        # Its end of repair became a TO_SERVICE, so its heap entry is outdated.
        self._machines_to_reschedule.add(id(machine_to_replace))
        return True

    def handle_purchase_replacement(
        self, next_event: Event, machine_simulation: "MaintenanceItemSimulation"
    ):
        machine = cast(MachineModel, machine_simulation.maintenance_item)
        part_simulations = [part.get_maintenance_item_simulation(self) for part in machine.spare_parts]

        # A new machine starts with no wear, and comes with new parts.
        machine_simulation.wear_age = 0
        for part_simulation in part_simulations:
            part_simulation.runtime = 0
            part_simulation.wear_age = 0

        replacement_event = Event(
            start_time=next_event.start_time, end_time=next_event.end_time,
            event_type=EventType.PURCHASE_REPLACEMENT,
            maintenance_item=machine, cost=next_event.cost,
        )
        self.purchase_cost += next_event.cost
        replacement_event.add_to_machine_events(machine_simulation)
        replacement_event.add_to_simulation_events(self)
        machine_simulation.runtime = max(machine_simulation.runtime, next_event.end_time)
        machine_simulation.mark_event_completed(replacement_event)

    def handle_preventive_maintenance(
        self, next_event: Event, machine_simulation: "MaintenanceItemSimulation",
        simulation_machines: List[MachineModel],
    ):
        machine = cast(MachineModel, machine_simulation.maintenance_item)
        machine_parts = machine.spare_parts

        # Wear up to the start of the PM. Wear is operating time, not the
        # calendar time of the slot: it only grows while the machine was in
        # service. Time on standby or under repair moves the calendar clock
        # (runtime) but adds no wear, for the machine or its parts.
        was_active = machine.status == MachineStatusEnum.ACTIVE
        elapsed = next_event.start_time - machine_simulation.runtime
        if was_active and elapsed > 0:
            wear_elapsed = self._wear_elapsed(machine_simulation, elapsed)
            machine_simulation.wear_age += wear_elapsed
            for part in machine_parts:
                part_simulation = part.get_maintenance_item_simulation(self)
                part_simulation.runtime += elapsed
                part_simulation.wear_age += wear_elapsed

        pm_cycle_year = machine.get_pm_year(int(next_event.start_time))
        if pm_cycle_year is None:
            machine_simulation.runtime = next_event.start_time + 0.001
            return

        # Parts of this machine that get replaced in this PM year
        pm_year_parts = pm_cycle_year.preventive_maintenance_parts
        pm_machine_parts: List[SparePartModel] = []
        for part_type in pm_year_parts:
            matching_part = find_obj_by_attr(machine_parts, "part_type", part_type.spare_part_type)
            if matching_part is not None:
                pm_machine_parts.append(matching_part)

        pm_cost = pm_cycle_year.pm_year_cost
        self.preventive_maintenance_cost += pm_cost
        pm_duration = pm_cycle_year.preventive_maintenance_hours

        pm_event = Event(
            start_time=next_event.start_time,
            end_time=next_event.start_time + (pm_duration / 8760),
            event_type=EventType.PREVENTIVE_MAINTENANCE,
            maintenance_item=machine, cost=pm_cost,
        )
        pm_event.add_to_machine_events(machine_simulation)
        pm_event.add_to_simulation_events(self)

        # The machine can't be used during the PM, whether or not a standby
        # takes its place: availability counts machines, and a standby that
        # covers is already one of them. Same as a repair in handle_failure.
        out_of_service_event = Event(
            start_time=pm_event.start_time, end_time=pm_event.end_time,
            event_type=EventType.OUT_OF_SERVICE, maintenance_item=machine,
        )
        out_of_service_event.add_to_machine_events(machine_simulation)
        out_of_service_event.add_to_simulation_events(self)

        # Parts replaced in this PM start again from new
        for part in pm_machine_parts:
            part_simulation = part.get_maintenance_item_simulation(self)
            part_simulation.runtime = 0
            part_simulation.wear_age = 0

        machine_simulation.runtime = max(machine_simulation.runtime, pm_event.end_time)
        machine_simulation.mark_event_completed(pm_event)

        # The machine is in the workshop for the PM. When it's done, the
        # END_OF_MAINTENANCE sends it where a repaired machine goes: back to
        # standby if the fleet has a pool (a standby took its place), straight
        # into service if it has none. Without this, a machine covered by a
        # standby stayed in service as well, and the pool emptied after the
        # first round of PMs. A machine already under repair keeps the repair's
        # own END_OF_MAINTENANCE.
        if machine.status in (MachineStatusEnum.ACTIVE, MachineStatusEnum.STANDBY):
            machine.status = MachineStatusEnum.MAINTENANCE
            end_of_pm_event = Event(
                start_time=pm_event.end_time, end_time=pm_event.end_time,
                event_type=EventType.END_OF_MAINTENANCE, maintenance_item=machine,
            )
            end_of_pm_event.add_to_simulation_events(self, upcoming=True)
            end_of_pm_event.add_to_machine_events(machine_simulation, upcoming=True)

        if was_active:
            # If no standby is free, replace_machine can turn this END_OF_MAINTENANCE
            # into a TO_SERVICE, so the machine goes straight back into service.
            self.replace_machine(
                gap_start_time=next_event.start_time,
                machine=machine,
                machine_simulation=machine_simulation,
                simulation_machines=simulation_machines,
            )

    def handle_to_service(
        self, next_event: Event, machine_simulation: "MaintenanceItemSimulation"
    ):
        machine = cast(MachineModel, machine_simulation.maintenance_item)
        machine.status = MachineStatusEnum.ACTIVE
        next_event.remove_from_simulation_events(self, upcoming=True)
        next_event.remove_from_machine_events(machine_simulation, upcoming=True)
        next_event.add_to_simulation_events(self)
        next_event.add_to_machine_events(machine_simulation)

    def handle_end_of_maintenance(
        self, next_event: Event, machine_simulation: "MaintenanceItemSimulation"
    ):
        machine = cast(MachineModel, machine_simulation.maintenance_item)
        no_standby_pool = self.alternative.normal_threshold >= self.alternative.machine_number
        machine.status = MachineStatusEnum.ACTIVE if no_standby_pool else MachineStatusEnum.STANDBY
        next_event.remove_from_simulation_events(self, upcoming=True)
        next_event.remove_from_machine_events(machine_simulation, upcoming=True)
        next_event.add_to_simulation_events(self)
        next_event.add_to_machine_events(machine_simulation)
        machine_simulation.runtime = next_event.start_time
