"""
alternative.py

An Alternative is one fleet configuration to evaluate: fleet size, replacement
period, horizon, availability targets and number of Monte Carlo runs. Creating
one runs all its simulations straight away and stores the averaged results.
"""
from __future__ import annotations
from typing import List, Union
from .simulation import Simulation
from .parallel import SimulationResult
from db.models import MachineTypeEnum


class Alternative:
    """
    One fleet configuration and the averaged results of its simulation runs.

    normal_threshold is the number of machines in use in normal operation (the
    rest start on standby), and crisis_threshold is the number needed in a crisis.
    Costs and availabilities are means over the `simulation_number` runs, and
    total_cost is rounded to the euro. Any extra keyword argument (for example
    a qualitative score) is stored as an attribute so it can be used as a criterion.
    """
    def __init__(self, name: str, machine_number: int, replacement_period: int,
                 period: int, simulation_number: int, normal_threshold: int = 36,
                 crisis_threshold: int = 44,
                 machine_type: MachineTypeEnum = MachineTypeEnum.VENTILATOR,
                 session_days: list | None = None,
                 shift_durations: list[float] | None = None,
                 parallel: bool = False,
                 max_workers: int | None = None,
                 **kwargs):
        self.name = name
        self.machine_number = machine_number
        self.replacement_period = replacement_period
        self.period = period
        self.purchase_cost = 0
        self.simulation_number = simulation_number
        self.corrective_maintenance_cost = 0
        self.preventive_maintenance_cost = 0
        self.total_cost = 0
        self.simulations: List[Union[Simulation, SimulationResult]] = []
        self.normal_threshold: int = normal_threshold
        self.crisis_threshold: int = crisis_threshold
        self.normal_availability: float = 0
        self.crisis_availability: float = 0
        self.machine_type: MachineTypeEnum = machine_type
        self.session_days: list = session_days if session_days is not None else [0, 1, 2, 3, 4, 5, 6]
        self.shift_durations: list[float] = shift_durations if shift_durations else [24.0]
        self.parallel: bool = parallel
        self.max_workers: int | None = max_workers

        for key, value in kwargs.items():
            setattr(self, key, value)

        self.execute_simulation()

    def execute_simulation(self):
        from classes.parallel import run_replications

        corrective_cost_sum = 0
        preventive_cost_sum = 0
        purchase_cost_sum = 0
        normal_availability_sum = 0
        crisis_availability_sum = 0

        workers = self.max_workers if self.parallel else 1
        runs = run_replications(self, self.simulation_number, max_workers=workers)

        for run in runs:
            corrective_cost_sum += run.corrective_maintenance_cost
            preventive_cost_sum += run.preventive_maintenance_cost
            purchase_cost_sum += run.purchase_cost
            normal_availability_sum += run.normal_availability
            crisis_availability_sum += run.crisis_availability

        run_count = self.simulation_number
        self.corrective_maintenance_cost = corrective_cost_sum / run_count
        self.preventive_maintenance_cost = preventive_cost_sum / run_count
        self.purchase_cost               = purchase_cost_sum / run_count
        self.normal_availability         = normal_availability_sum / run_count
        self.crisis_availability         = crisis_availability_sum / run_count
        self.total_cost = round(
            self.corrective_maintenance_cost
            + self.preventive_maintenance_cost
            + self.purchase_cost
        )

    def to_dict(self):
        result = {}
        for key, value in self.__dict__.items():
            if key != "simulations":
                result[key] = value
        return result

    def __repr__(self):
        return f"Alternative: {self.to_dict()}"
