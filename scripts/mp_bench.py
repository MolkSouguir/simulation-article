"""
Proof-of-concept: run Monte Carlo simulation replications across worker
processes instead of sequentially in one process.

Each worker independently calls load_config() (own DB connection, own
db_machines) and runs its share of replications, returning only plain
floats — never any SQLAlchemy-backed object — to avoid the pickling
problems that live MachineModel/SparePartModel instances run into.

Usage:
    python -m scripts.mp_bench [simulation_number] [workers]
"""
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass


@dataclass
class BatchResult:
    n: int
    cm_cost_sum: float
    pm_cost_sum: float
    pc_cost_sum: float
    nm_avl_sum: float
    cr_avl_sum: float


def run_batch(machine_number: int, replacement_period: int, period: int,
              normal_threshold: int, crisis_threshold: int, n: int) -> BatchResult:
    """Runs n replications in this worker process and returns aggregated sums only."""
    from db.loader import load_config
    from classes.simulation import Simulation
    from classes.alternative import Alternative
    from db.models import MachineTypeEnum

    load_config()

    # Throwaway Alternative shell so Simulation() has the interface it
    # expects, but we never pickle this object back to the parent process.
    alt = Alternative.__new__(Alternative)
    alt.name = "worker-batch"
    alt.machine_number = machine_number
    alt.replacement_period = replacement_period
    alt.period = period
    alt.normal_threshold = normal_threshold
    alt.crisis_threshold = crisis_threshold
    alt.machine_type = MachineTypeEnum.VENTILATOR
    alt.session_days = [0, 1, 2, 3, 4, 5, 6]
    alt.shift_durations = [24.0]
    alt.simulations = []

    cm = pm = pc = nm = cr = 0.0
    for _ in range(n):
        sim = Simulation(
            alternative=alt,
            machine_number=machine_number,
            normal_threshold=normal_threshold,
            crisis_threshold=crisis_threshold,
            machine_type=alt.machine_type,
        )
        cm += sim.corrective_maintenance_cost
        pm += sim.preventive_maintenance_cost
        pc += sim.purchase_cost
        nm += sim.normal_availability
        cr += sim.crisis_availability

    return BatchResult(n=n, cm_cost_sum=cm, pm_cost_sum=pm, pc_cost_sum=pc,
                        nm_avl_sum=nm, cr_avl_sum=cr)


def run_sequential(machine_number, replacement_period, period,
                    normal_threshold, crisis_threshold, simulation_number) -> tuple[dict, float]:
    from db.loader import load_config
    from classes.alternative import Alternative
    from db.models import MachineTypeEnum

    load_config()
    t0 = time.time()
    alt = Alternative(
        name="sequential", machine_number=machine_number,
        replacement_period=replacement_period, period=period,
        simulation_number=simulation_number,
        normal_threshold=normal_threshold, crisis_threshold=crisis_threshold,
        machine_type=MachineTypeEnum.VENTILATOR,
    )
    elapsed = time.time() - t0
    return {
        "total_cost": alt.total_cost,
        "normal_availability": alt.normal_availability,
        "crisis_availability": alt.crisis_availability,
    }, elapsed


def run_parallel(machine_number, replacement_period, period,
                  normal_threshold, crisis_threshold, simulation_number, workers) -> tuple[dict, float]:
    base = simulation_number // workers
    rem = simulation_number % workers
    batch_sizes = [base + (1 if i < rem else 0) for i in range(workers)]
    batch_sizes = [b for b in batch_sizes if b > 0]

    t0 = time.time()
    with ProcessPoolExecutor(max_workers=len(batch_sizes)) as pool:
        futures = [
            pool.submit(run_batch, machine_number, replacement_period, period,
                        normal_threshold, crisis_threshold, n)
            for n in batch_sizes
        ]
        results = [f.result() for f in futures]
    elapsed = time.time() - t0

    n_total = sum(r.n for r in results)
    cm = sum(r.cm_cost_sum for r in results) / n_total
    pm = sum(r.pm_cost_sum for r in results) / n_total
    pc = sum(r.pc_cost_sum for r in results) / n_total
    nm = sum(r.nm_avl_sum for r in results) / n_total
    cr = sum(r.cr_avl_sum for r in results) / n_total
    total_cost = round(cm + pm + pc)
    return {
        "total_cost": total_cost,
        "normal_availability": nm,
        "crisis_availability": cr,
    }, elapsed


if __name__ == "__main__":
    import sys

    machine_number = 38
    replacement_period = 7
    period = 15
    normal_threshold = 36
    crisis_threshold = 44
    simulation_number = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 8

    print(f"Running {simulation_number} simulations sequentially...")
    seq_result, seq_time = run_sequential(machine_number, replacement_period, period,
                                           normal_threshold, crisis_threshold, simulation_number)
    print(f"  sequential: {seq_time:.2f}s -> {seq_result}")

    print(f"\nRunning {simulation_number} simulations across {workers} worker processes...")
    par_result, par_time = run_parallel(machine_number, replacement_period, period,
                                         normal_threshold, crisis_threshold, simulation_number, workers)
    print(f"  parallel:   {par_time:.2f}s -> {par_result}")

    print(f"\nSpeedup: {seq_time / par_time:.2f}x")
    print(f"Sequential total_cost={seq_result['total_cost']:,} vs "
          f"parallel total_cost={par_result['total_cost']:,} "
          f"(diff {abs(seq_result['total_cost'] - par_result['total_cost']) / seq_result['total_cost'] * 100:.1f}% "
          f"- expected to differ since these are independent random draws, not the same seed)")
