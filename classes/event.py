"""
event.py

Event is the basic record of the simulation. Anything that happens during a run
(a failure, a repair, a PM, a replacement, a machine swap) is stored as an Event.

The Simulation and each MaintenanceItemSimulation keep two lists of events:
`events` for the ones that already happened and `upcoming_events` for the ones
planned in the future (for example the end of a repair).
"""
from __future__ import annotations
from .event_type import EventType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import MachineModel, SparePartModel
    from .simulation import Simulation
    from .maintenance_item_simulation import MaintenanceItemSimulation

class Event:
    """
    Something that happens at a given time in a simulation run.

    Times are in simulation years. Instantaneous events (FAILURE,
    PURCHASE_REPLACEMENT, ...) have end_time == start_time. `cost` is 0 for
    events that don't cost anything, and `maintenance_item` is None only for
    START_OF_SIMULATION.
    """
    def __init__(
        self,
        start_time: float,
        end_time: float,
        event_type: EventType,
        maintenance_item: "MachineModel | SparePartModel | None",
        cost: float = 0
        ):

        if maintenance_item != None:
            description = str(event_type.value) + " of " + maintenance_item.name + " " + maintenance_item.code
        else:
            description = ""

        self.start_time = start_time
        self.end_time = end_time
        self.duration = end_time - start_time
        self.event_type = event_type
        self.description = description
        self.maintenance_item = maintenance_item
        self.cost = cost
        self.simulation: Simulation | None = None
        self.maintenance_item_simulation: MaintenanceItemSimulation | None = None

    def add_to_simulation_events(self, simulation: Simulation, upcoming: bool = False):
        self.simulation = simulation
        if upcoming:
            simulation.upcoming_events.append(self)
        else:
            simulation.events.append(self)


    def add_to_machine_events(self, maintenance_item_simulation: MaintenanceItemSimulation, upcoming: bool = False):
        self.maintenance_item_simulation = maintenance_item_simulation
        if upcoming:
            maintenance_item_simulation.upcoming_events.append(self)
        else:
            maintenance_item_simulation.events.append(self)

    # The event may already be gone from the list when we remove it, so a
    # missing entry is simply ignored.

    def remove_from_simulation_events(self, simulation: Simulation, upcoming: bool = False):
        self.simulation = None
        try:
            if upcoming:
                simulation.upcoming_events.remove(self)
            else:
                simulation.events.remove(self)
        except ValueError:
            return

    def remove_from_machine_events(self,  maintenance_item_simulation: MaintenanceItemSimulation, upcoming: bool = False):
        self.maintenance_item_simulation = None
        try:
            if upcoming:
                maintenance_item_simulation.upcoming_events.remove(self)
            else:
                maintenance_item_simulation.events.remove(self)
        except ValueError:
            return
