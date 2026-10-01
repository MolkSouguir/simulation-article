import matplotlib.pyplot as plt
from database import simulations
from classes.event_type import EventType
from scipy.integrate import quad
from scipy.interpolate import interp1d
import os
import math
from collections import defaultdict


def get_unique_filename(directory, base_name, extension):
    """
    Get a unique filename in the directory, adding (1), (2), etc. if file exists.
    Similar to Windows file naming behavior.

    Args:
        directory: The directory path
        base_name: The base filename without extension
        extension: The file extension (e.g., '.png')

    Returns:
        Full path to a unique filename
    """
    # Create directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)

    # Try the base filename first
    filepath = os.path.join(directory, f"{base_name}{extension}")
    if not os.path.exists(filepath):
        return filepath

    # If exists, try adding (1), (2), etc.
    counter = 1
    while True:
        filepath = os.path.join(directory, f"{base_name} ({counter}){extension}")
        if not os.path.exists(filepath):
            return filepath
        counter += 1


def calculate_availability_timeline(simulation_key="simulation-1", total_machines=45, period=15):

    #Validation for calling the wrong simulation key
    if simulation_key not in simulations:
        print(f"Simulation {simulation_key} not found!")
        return None, None, None

    events = simulations[simulation_key]

    # collecting all out of service events as these are the events that hold the
    # the information of how long I needed a machine for a slot and I didn't have any availabe.
    maintenance_periods = []

    # Also collect all unique time points where events happen
    time_points = set()
    time_points.add(0)  # Add start time
    time_points.add(period)  # Add end time to ensure full period coverage

    for event in events:
        current_time = event.start_time
        time_points.add(current_time)

        # Track OUT_OF_SERVICE events and adding the timepoints to my unordered list
        if event.event_type == EventType.OUT_OF_SERVICE:
            machine = event.maintenance_item
            if machine:
                machine_name = getattr(machine, 'name', str(machine))
                # Find the corresponding END_OF_MAINTENANCE event
                # The maintenance duration is the MTTR (end_time - start_time)
                maintenance_end = event.end_time
                # I am creating a maintenance period for this event
                maintenance_periods.append({
                    'machine': machine_name,
                    'start': current_time,
                    'end': maintenance_end,
                    'duration': maintenance_end - current_time
                })
                time_points.add(maintenance_end)

    # Sort time points
    sorted_times = sorted(time_points)

    # For each time point, count how many maintenance periods are active
    times = []
    available_machines = []
    events_info = []

    for t in sorted_times:
        # Count overlapping maintenance periods at time t
        # Use a SET to track unique machines (avoid counting same machine multiple times)
        machines_in_maintenance_set = set()

        for period in maintenance_periods:
            # An out of service period is active if: start <= t < end
            if period['start'] <= t < period['end']:
                machines_in_maintenance_set.add(period['machine'])

        # Count unique machines in maintenance
        machines_in_maintenance = len(machines_in_maintenance_set)

        # Available machines = Total machines - Machines in maintenance
        available = total_machines - machines_in_maintenance

        times.append(t)
        available_machines.append(available)

        if machines_in_maintenance > 0:
            info = f"{t:.2f}y: {machines_in_maintenance} in maintenance, {available} available"
        else:
            info = f"{t:.2f}y: All machines available"
        events_info.append(info)

    return times, available_machines, events_info


def plot_availability(times, availability, threshold=36, period=15, total_machines=45, crisis_threshold=None, machine_number=None, replacement_period=None):

    plt.figure(figsize=(16, 24))

    # Calculate machines in maintenance
    machines_in_maintenance = [total_machines - a for a in availability]

    # Build title with alternative info
    title_parts = ['System Availability Over Time']
    if machine_number is not None and replacement_period is not None and period is not None:
        title_parts.append(f'({machine_number} machines, replacing every {replacement_period} years)')
    title = '\n'.join(title_parts)

    # Plot 1: Available machines over time
    plt.subplot(3, 1, 1)
    plt.plot(times, availability, 'black', linewidth=1, label='Available Machines')
    plt.axhline(y=threshold, color='teal', linestyle='--', linewidth=2,
                label=f'Normal Threshold ({threshold} machines)')

    # Add crisis threshold if provided
    if crisis_threshold is not None:
        plt.axhline(y=crisis_threshold, color='brown', linestyle='--', linewidth=2,
                    label=f'Crisis Threshold ({crisis_threshold} machines)')

    # Highlight periods below normal threshold only
    below_normal = [(t, a) for t, a in zip(times, availability) if a < threshold]

    if below_normal:
        below_times, below_avail = zip(*below_normal)
        plt.scatter(below_times, below_avail, color='#FF6B6B', s=100, zorder=5,
                   label='Below Normal Threshold', marker='x')

    plt.xlabel('Time (years)', fontsize=16)
    plt.ylabel('Available Machines', fontsize=16)
    plt.title(title, fontsize=18, fontweight='bold')
    plt.grid(True, alpha=0.3, axis='y')
    plt.legend(fontsize=14)
    plt.xlim(0, period)

    # Set y-axis to show up to crisis threshold + 1, or total_machines + 1 if no crisis threshold
    y_max = (crisis_threshold + 1) if crisis_threshold is not None else (total_machines + 1)
    plt.ylim(24, y_max)
    plt.yticks(range(24, int(y_max) + 1, 2))  # Tick marks every 5 machines
    plt.tick_params(axis='both', labelsize=14)  # Increase tick label font size

    # Save to assets folder with unique filename
    filepath = get_unique_filename('assets', 'availability_timeline', '.png')
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\nPlot saved as '{filepath}'")


def plot_failures_over_time(simulation_key="simulation-1", period=15, machine_number=None, replacement_period=None):

    if simulation_key not in simulations:
        print(f"Simulation {simulation_key} not found!")
        return

    events = simulations[simulation_key]

    # Extract all failure events
    failure_events = [e for e in events if e.event_type == EventType.FAILURE]

    if not failure_events:
        print(f"No failure events found in {simulation_key}")
        return

    # Sort by time
    failure_events.sort(key=lambda e: e.start_time)

    # Create cumulative failure data
    failure_times = [0.0]  # Start at time 0 with 0 failures
    cumulative_failures = [0]

    for i, event in enumerate(failure_events, start=1):
        failure_times.append(float(event.start_time))
        cumulative_failures.append(i)

    # Add final point at end of period
    failure_times.append(period)
    cumulative_failures.append(len(failure_events))

    # Build title with alternative info
    title = f'Failure events Over Time'
    if machine_number is not None and replacement_period is not None and period is not None:
        title += f'\n({machine_number} machines, replacing every {replacement_period} years)'

    # Create the plot
    plt.figure(figsize=(12, 6))

    plt.step(failure_times, cumulative_failures, where='post', linewidth=2, color='black')
    

    plt.xlabel('Time (years)', fontsize=16)
    plt.ylabel('Cumulative Number of Failures', fontsize=16)
    plt.title(title, fontsize=18, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.xlim(0, period)
    plt.ylim(0, max(cumulative_failures) * 1.1)
    plt.legend(fontsize=14)
    plt.tick_params(axis='both', labelsize=14)  # Increase tick label font size

    plt.tight_layout()

    # Save to assets folder with unique filename
    filepath = get_unique_filename('assets', f'failure_events_cumulative', '.png')
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\nFailures plot saved as '{filepath}'")

    return filepath


def plot_failure_rate(simulation_key="simulation-1", period=15, window_size=1.0, machine_number=None, replacement_period=None):

    if simulation_key not in simulations:
        print(f"Simulation {simulation_key} not found!")
        return

    events = simulations[simulation_key]

    # Extract all failure events
    failure_events = [e for e in events if e.event_type == EventType.FAILURE]

    if not failure_events:
        print(f"No failure events found in {simulation_key}")
        return

    # Sort by time
    failure_events.sort(key=lambda e: e.start_time)
    failure_times = [e.start_time for e in failure_events]

    # Calculate failure rate using sliding windows
    time_points = []
    failure_rates = []

    # Create time points at regular intervals
    num_intervals = int(period / window_size)
    for i in range(num_intervals):
        window_start = i * window_size
        window_end = (i + 1) * window_size
        window_center = (window_start + window_end) / 2

        # Count failures in this window
        failures_in_window = sum(1 for t in failure_times if window_start <= t < window_end)

        # Calculate rate (failures per year)
        rate = failures_in_window / window_size

        time_points.append(window_center)
        failure_rates.append(rate)

    # Build title with alternative info
    title = f'Failure Events Over Time'
    if machine_number is not None and replacement_period is not None and period is not None:
        title += f'\n({machine_number} machines, replacing every {replacement_period} years)'

    # Create the plot
    plt.figure(figsize=(12, 6))

    # Line chart for failure rates
    plt.plot(time_points, failure_rates, color='black', linewidth=2.5,
             label='Failure Events')

    # Add average line
    avg_rate = len(failure_events) / period
    plt.axhline(y=avg_rate, color='#2ECC71', linestyle='--', linewidth=2,
                label=f'Average failures ({avg_rate:.2f} failures/year)')

    plt.xlabel('Time (years)', fontsize=16)
    plt.ylabel('Failure events', fontsize=16)
    plt.title(title, fontsize=18, fontweight='bold')
    plt.grid(True, alpha=0.3, axis='y')
    plt.xlim(0, period)
    plt.ylim(0, max(failure_rates) * 1.2 if failure_rates else 1)
    plt.legend(fontsize=14)
    plt.tick_params(axis='both', labelsize=14)  # Increase tick label font size

    # Add statistics text box
    total_failures = len(failure_events)

    stats_text = (f'Total Failures: {total_failures}\n')
    plt.text(0.98, 0.98, stats_text, transform=plt.gca().transAxes,
             fontsize=14, verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()

    # Save to assets folder with unique filename
    filepath = get_unique_filename('assets', f'failure_events', '.png')
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\nFailure events plot saved as '{filepath}'")

    return filepath


def main(total_machines=45, threshold=36, period=15, simulation_key="simulation-1", crisis_threshold=None, machine_number=None, replacement_period=None): # these are the default values if I don't specify them

    print("Loading simulation data...")

    if not simulations:
        print("\nERROR: No simulation data found!")
        print("\nPlease run the simulation first:")
        print("  python app.py")
        print("\nThen run this script:")
        print("  python track_availability.py")
        return

    print(f"Found {len(simulations)} simulation(s)")

    print(f"\nConfiguration:")
    print(f"  Total machines: {total_machines}")
    print(f"  Threshold: {threshold} machines")
    print(f"  Period: {period} years")

    print(f"\nAnalyzing {simulation_key}...")
    times, availability, events_info = calculate_availability_timeline(
        simulation_key=simulation_key,
        total_machines=total_machines,
        period=period
    )

    if times is None:
        return

    # Plot results
    print("\nGenerating plot...")
    plot_availability(
        times,
        availability,
        threshold=threshold,
        period=period,
        total_machines=total_machines,
        crisis_threshold=crisis_threshold,
        machine_number=machine_number,
        replacement_period=replacement_period
    )


def analyze_failure_rates(simulation_key="simulation-1", period=15):
    if simulation_key not in simulations:
        print(f"Simulation {simulation_key} not found!")
        return

    events = simulations[simulation_key]

    # Extract failure events
    failure_events = [e for e in events if e.event_type == EventType.FAILURE]

    if not failure_events:
        print(f"No failure events found in {simulation_key}")
        return

    # Group failures by part type and count unique parts
    failures_by_part = defaultdict(list)
    unique_parts_by_type = defaultdict(set)

    for event in failure_events:
        if event.maintenance_item is None:
            continue

        # Get part type and parameters
        part = event.maintenance_item
        part_type = getattr(part, 'spare_part_type', None)
        part_name = getattr(part, 'name', None)

        if part_type and part_name:
            part_type_name = part_type.value if hasattr(part_type, 'value') else str(part_type)
            eta = getattr(part, 'eta', None)
            beta = getattr(part, 'beta', None)

            if eta and beta:
                failures_by_part[part_type_name].append({
                    'eta': eta,
                    'beta': beta,
                    'time': event.start_time
                })
                # Track unique parts that failed to estimate total count
                unique_parts_by_type[part_type_name].add(part_name)

    # Calculate and display results
    print("\n" + "="*80)
    print("FAILURE RATE ANALYSIS - Expected vs. Actual")
    print("="*80)
    print(f"\nSimulation: {simulation_key}")
    print(f"Period: {period} years\n")
    print(f"{'Part Type':<20} {'Count':<8} {'eta':<8} {'beta':<8} {'MTTF':<8} {'Exp/Part':<10} {'Expected':<10} {'Actual':<10} {'Diff':<10}")
    print("-" * 102)

    total_expected = 0
    total_actual = 0

    for part_type, failure_list in sorted(failures_by_part.items()):
        if not failure_list:
            continue

        # Use first occurrence for parameters (should be same for all parts of same type)
        eta = failure_list[0]['eta']
        beta = failure_list[0]['beta']

        # Calculate MTTF = eta * Gamma(1 + 1/beta)
        mttf = eta * math.gamma(1 + 1/beta)

        # Count unique parts of this type (estimate based on parts that failed)
        # This is a rough estimate - ideally we'd count all parts in the system
        num_parts = len(unique_parts_by_type[part_type])

        # Expected failures for ONE part over the period (without PM)
        expected_per_part = period / mttf

        # Expected failures for ALL parts of this type
        expected_failures = expected_per_part * num_parts

        # Actual failures
        actual_failures = len(failure_list)

        # Difference
        difference = actual_failures - expected_failures
        difference_str = f"{difference:+.1f}"

        total_expected += expected_failures
        total_actual += actual_failures

        print(f"{part_type:<20} {num_parts:<8} {eta:<8.2f} {beta:<8.2f} {mttf:<8.2f} {expected_per_part:<10.2f} {expected_failures:<10.1f} {actual_failures:<10} {difference_str:<10}")

    print("-" * 102)
    total_diff_str = f"{(total_actual - total_expected):+.1f}"
    print(f"{'TOTAL':<20} {'':<8} {'':<8} {'':<8} {'':<8} {'':<10} {total_expected:<10.1f} {total_actual:<10} {total_diff_str:<10}")


    return failures_by_part


if __name__ == "__main__":
    main()
