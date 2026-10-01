"""
classes/parallel.py

Runs the replications of an Alternative in several worker processes.

Workers never receive or send back live SQLAlchemy objects (MachineModel,
SparePartModel, Event): with Windows' 'spawn' start method those don't pickle.
Each worker loads the configuration itself and returns only plain numbers,
wrapped in a SimulationResult.

Replication 1 always runs in the main process so that
database.simulations["simulation-1"] holds real Event objects. The timeline
and availability charts read that key.

The same stand-in is used without workers too: see run_replications.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.alternative import Alternative
    from db.models import MachineTypeEnum


@dataclass
class SimulationResult:
    """Lightweight stand-in for a finished Simulation, small enough to keep
    thousands of and plain enough to cross process boundaries.

    It only carries what persistence and the statistics read. `events` is
    always empty: only replication 1 keeps its events.
    """
    simulation_number: int
    purchase_cost: float
    corrective_maintenance_cost: float
    preventive_maintenance_cost: float
    normal_availability: float
    crisis_availability: float
    resilience: dict = field(default_factory=dict)
    events: list = field(default_factory=list)


def _run_batch(machine_number: int, replacement_period: int, period: int,
               normal_threshold: int, crisis_threshold: int,
               machine_type: "MachineTypeEnum",
               session_days: list, shift_durations: list,
               replication_count: int) -> list[SimulationResult]:
    """Run `replication_count` replications inside one worker process.

    This is the function the worker processes start from, so the imports are
    kept local: with 'spawn' the module is re-imported in every worker.
    """
    from db.loader import load_config
    from classes.simulation import Simulation
    from classes.alternative import Alternative

    load_config()

    shell = Alternative.__new__(Alternative)
    shell.machine_number = machine_number
    shell.replacement_period = replacement_period
    shell.period = period
    shell.normal_threshold = normal_threshold
    shell.crisis_threshold = crisis_threshold
    shell.machine_type = machine_type
    shell.session_days = session_days
    shell.shift_durations = shift_durations
    shell.simulations = []

    results = []
    for _ in range(replication_count):
        simulation = Simulation(
            alternative=shell, machine_number=machine_number,
            normal_threshold=normal_threshold, crisis_threshold=crisis_threshold,
            machine_type=machine_type,
        )
        result = summarize(simulation)
        result.simulation_number = 0  # numbered by the caller once every batch is back
        results.append(result)
    return results


def summarize(simulation) -> SimulationResult:
    """The numbers of a finished replication, without its events and fleet copy."""
    return SimulationResult(
        simulation_number=simulation.simulation_number,
        purchase_cost=simulation.purchase_cost,
        corrective_maintenance_cost=simulation.corrective_maintenance_cost,
        preventive_maintenance_cost=simulation.preventive_maintenance_cost,
        normal_availability=simulation.normal_availability,
        crisis_availability=simulation.crisis_availability,
        resilience=simulation.resilience,
    )


def run_replications(alternative: "Alternative", simulation_number: int,
                      max_workers: int | None = None) -> list:
    """
    Run `simulation_number` replications for the alternative and add them to
    `alternative.simulations`.

    With max_workers <= 1 (the default) this is a plain loop in this process.
    With more workers, replications 2..N run in worker processes.

    Either way only replication 1 is kept as a real Simulation with its
    events: the charts and the daily-hours criteria read it. Replications
    2..N are SimulationResult stand-ins holding just their numbers, which is
    all the statistics and the database need. A full replication takes a few
    MB (thousands of events and a copy of the fleet), so keeping them all
    would run out of memory on runs of thousands of replications.

    Returns all results in order, the first one a Simulation.
    """
    from classes.simulation import Simulation

    effective_workers = max_workers or 1

    if simulation_number <= 1 or effective_workers <= 1:
        results = []
        for replication_index in range(simulation_number):
            simulation = Simulation(
                alternative=alternative, machine_number=alternative.machine_number,
                normal_threshold=alternative.normal_threshold,
                crisis_threshold=alternative.crisis_threshold,
                machine_type=alternative.machine_type,
            )
            kept = simulation if replication_index == 0 else summarize(simulation)
            alternative.simulations.append(kept)
            results.append(kept)
        return results

    first = Simulation(
        alternative=alternative, machine_number=alternative.machine_number,
        normal_threshold=alternative.normal_threshold,
        crisis_threshold=alternative.crisis_threshold,
        machine_type=alternative.machine_type,
    )
    alternative.simulations.append(first)

    # Split the remaining replications as evenly as possible over the workers.
    remaining = simulation_number - 1
    workers = max(1, min(effective_workers, remaining, os.cpu_count() or 1))
    per_worker, leftover = divmod(remaining, workers)
    batch_sizes = [
        size
        for size in (per_worker + (1 if worker_index < leftover else 0) for worker_index in range(workers))
        if size > 0
    ]

    batch_results: list[SimulationResult] = []
    with ProcessPoolExecutor(max_workers=len(batch_sizes)) as pool:
        futures = [
            pool.submit(
                _run_batch, alternative.machine_number, alternative.replacement_period,
                alternative.period, alternative.normal_threshold, alternative.crisis_threshold,
                alternative.machine_type,
                alternative.session_days, alternative.shift_durations,
                batch_size,
            )
            for batch_size in batch_sizes
        ]
        for future in futures:
            batch_results.extend(future.result())

    all_results = [first, *batch_results]
    for number, result in enumerate(all_results, start=1):
        result.simulation_number = number

    alternative.simulations.extend(batch_results)
    return all_results
