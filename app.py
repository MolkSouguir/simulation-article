"""
app.py

Runs one fleet configuration from the command line and shows its charts.

The fleet (machines, spare parts, PM schedules) comes from the database, see
db/loader.py. Change it there, not here. On a new database, fill it first:
    python -m db.seed

Then:
    python app.py

The settings are at the top of the __main__ block: fleet size (38),
replacement period (7 years), horizon (15 years), number of Monte Carlo runs
(1), and the normal and crisis thresholds (36 and 44 machines).

Careful: every run empties the assets/ folder first.
"""
from db.session import ensure_postgres_ready
from db.loader import load_config
from services.simulation_service import run_simulation

ensure_postgres_ready()
load_config()

if __name__ == "__main__":
    from visualization.timeline import plot_simulation_timeline
    import time
    import os

    # Start from an empty assets/ folder so old charts don't get mixed in
    os.makedirs('assets', exist_ok=True)
    for filename in os.listdir('assets'):
        file_path = os.path.join('assets', filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as delete_error:
            print(f"Error deleting {file_path}: {delete_error}")

    print("Assets folder ready and cleared.")

    machine_number = 38
    replacement_period = 7
    period = 15
    simulation_number = 1
    machine_threshold = 36
    crisis_threshold = 44

    print("\nRunning simulation...")
    start_time = time.time()
    new_alternative, db_id = run_simulation(
        name="Alternative1",
        machine_number=machine_number,
        replacement_period=replacement_period,
        period=period,
        simulation_number=simulation_number,
        normal_threshold=machine_threshold,
        crisis_threshold=crisis_threshold,
        persist=True,
    )
    end_time = time.time()
    elapsed_time = end_time - start_time

    print(f"Simulation complete! Generated {new_alternative.simulation_number} simulations.")
    print(f"Execution time: {elapsed_time:.2f} seconds ({elapsed_time/60:.2f} minutes)")

    # A quick look at the events of the first run
    from database import simulations
    if simulations:
        events = simulations["simulation-1"]
        start_times = [event.start_time for event in events]
        end_times = [event.end_time for event in events]

        print(f"\n--- Timing Analysis ---")
        print(f"Total events: {len(events)}")
        print(f"Time range: {min(start_times):.2f} to {max(end_times):.2f} years")
        print(f"Expected period: 15 years")

        from collections import Counter
        event_counts = Counter()
        for event in events:
            event_type_value = event.event_type.value
            event_label = event_type_value[0] if isinstance(event_type_value, tuple) else event_type_value
            event_counts[event_label] += 1

        print(f"\nEvent types:")
        for event_label, count in event_counts.most_common():
            print(f"  {event_label}: {count}")

    print("\nGenerating visualization for simulation-1...")
    figure = plot_simulation_timeline(
        "simulation-1",
        machine_number=machine_number,
        replacement_period=replacement_period,
        period=period
    )
    if figure:
        figure.show()
    else:
        print("No events to visualize.")

    fleet_size_text = str(new_alternative.machine_number)
    replacement_years_text = str(new_alternative.replacement_period)

    print("\n" + "="*80)
    print("TRACKING SYSTEM AVAILABILITY")
    print("="*80 + "\n")
    from visualization.availability import (
        main as track_availability_main,
        plot_failures_over_time,
        plot_failure_rate,
        analyze_failure_rates,
    )

    track_availability_main(
        total_machines=machine_number,
        threshold=machine_threshold,
        period=period,
        crisis_threshold=crisis_threshold,
        machine_number=machine_number,
        replacement_period=replacement_period,
    )

    print("\n" + "="*80)
    print("PLOTTING FAILURES OVER TIME")
    print("="*80 + "\n")

    plot_failures_over_time(
        simulation_key="simulation-1",
        period=period,
        machine_number=machine_number,
        replacement_period=replacement_period,
    )

    print("\n" + "="*80)
    print("PLOTTING FAILURE RATE OVER TIME")
    print("="*80 + "\n")

    plot_failure_rate(
        simulation_key="simulation-1",
        period=period,
        window_size=1.0,
        machine_number=machine_number,
        replacement_period=replacement_period,
    )

    analyze_failure_rates(simulation_key="simulation-1", period=period)

    print("\nAlternative of " + fleet_size_text + " machines with " + replacement_years_text + " replacement years.")
    print("Total Alternative cost: " + str(new_alternative.total_cost))
    print("Availability percentages - Normal: " + str(new_alternative.normal_availability) + " Crisis: " + str(new_alternative.crisis_availability))
