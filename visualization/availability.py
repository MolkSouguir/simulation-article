"""
visualization/availability.py

Availability and failure charts, built from the runs kept in
database.simulations: machines available over time, cumulative failures,
failure rate per year, and a table of expected against actual failures.
"""
import os
import math
from collections import defaultdict

import matplotlib.pyplot as plt
from scipy.integrate import quad
from scipy.interpolate import interp1d

from database import simulations
from classes.event_type import EventType
from functions.helper_functions import unit_name


def _unique_filename(directory: str, base_name: str, extension: str) -> str:
    """A file path that doesn't exist yet: adds (1), (2), ... to the name if needed."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{base_name}{extension}")
    if not os.path.exists(path):
        return path
    counter = 1
    while True:
        path = os.path.join(directory, f"{base_name} ({counter}){extension}")
        if not os.path.exists(path):
            return path
        counter += 1


def _title_with_alternative(title: str, machine_number, replacement_period) -> str:
    if machine_number and replacement_period:
        title += f"\n({machine_number} machines, replacing every {replacement_period} years)"
    return title


def calculate_availability_timeline(
    simulation_key: str = "simulation-1",
    total_machines: int = 45,
    period: int = 15,
):
    """
    Number of machines available at every moment it changes, from the
    OUT_OF_SERVICE events of one run.

    Returns three lists of the same length (times, available machines, a
    short text per time), or (None, None, None) if the run isn't found.
    """
    if simulation_key not in simulations:
        print(f"Simulation '{simulation_key}' not found.")
        return None, None, None

    events = simulations[simulation_key]
    maintenance_periods = []
    time_points = {0, period}

    for event in events:
        time_points.add(event.start_time)
        if event.event_type == EventType.OUT_OF_SERVICE and event.maintenance_item:
            machine_name = unit_name(event.maintenance_item)   # a part's downtime is its machine's
            maintenance_periods.append({
                'machine': machine_name,
                'start': event.start_time,
                'end': event.end_time,
            })
            time_points.add(event.end_time)

    times, available_machines, events_info = [], [], []
    for time_point in sorted(time_points):
        in_maintenance = {
            maintenance['machine'] for maintenance in maintenance_periods
            if maintenance['start'] <= time_point < maintenance['end']
        }
        available = total_machines - len(in_maintenance)
        times.append(time_point)
        available_machines.append(available)
        events_info.append(
            f"{time_point:.2f}y: {len(in_maintenance)} in maintenance, {available} available"
            if in_maintenance else f"{time_point:.2f}y: All machines available"
        )

    return times, available_machines, events_info


def availability_from_records(records: dict, total_machines: int, period: float):
    """
    Same numbers as calculate_availability_timeline, from the compact events
    of visualization.timeline.event_records (a saved run).

    Returns (times, available machines). A machine counts as down at time t
    when one of its OUT_OF_SERVICE spans has start <= t < end. The spans are
    swept in time order instead of being checked one by one at every time.
    """
    out_of_service = _event_type_label_value(EventType.OUT_OF_SERVICE)
    items = records["items"]
    time_points = {0, period}
    starts, ends = [], []
    for event_label, item_index, start_time, end_time, _, _ in records["events"]:
        time_points.add(start_time)
        if event_label == out_of_service and item_index >= 0:
            machine_name = items[item_index][1]   # the item's machine (a part's row is its machine)
            starts.append((start_time, machine_name))
            ends.append((end_time, machine_name))
            time_points.add(end_time)
    starts.sort()
    ends.sort()

    open_spans: dict[str, int] = defaultdict(int)   # machine -> spans covering the current time
    start_position = end_position = 0
    times, available_machines = [], []
    for time_point in sorted(time_points):
        while start_position < len(starts) and starts[start_position][0] <= time_point:
            open_spans[starts[start_position][1]] += 1
            start_position += 1
        while end_position < len(ends) and ends[end_position][0] <= time_point:
            machine_name = ends[end_position][1]
            open_spans[machine_name] -= 1
            if open_spans[machine_name] == 0:
                del open_spans[machine_name]
            end_position += 1
        times.append(time_point)
        available_machines.append(total_machines - len(open_spans))
    return times, available_machines


def _event_type_label_value(event_type: EventType) -> str:
    # EventType values are declared as 1-tuples, so unwrap them.
    return event_type.value[0] if isinstance(event_type.value, tuple) else event_type.value


def availability_figure(times, availability, machine_number: int, period: int,
                        normal_threshold: int, crisis_threshold: int, alternative_name: str | None = None):
    """Plotly chart of the machines available over time, with both thresholds."""
    import plotly.graph_objects as go

    figure = go.Figure()
    # The count holds from one time to the next and changes only at an event,
    # so it is drawn as steps (shape 'hv'), not as sloped lines between points.
    figure.add_trace(go.Scatter(
        x=times, y=availability,
        mode='lines', line=dict(color='black', width=2, shape='hv'),
        name='Available Machines',
    ))
    figure.add_hline(y=normal_threshold, line=dict(color='teal', dash='dash', width=2),
                     annotation_text=f'Normal threshold ({normal_threshold})')
    figure.add_hline(y=crisis_threshold, line=dict(color='brown', dash='dash', width=2),
                     annotation_text=f'Crisis threshold ({crisis_threshold})')

    # Mark every moment the fleet drops below the normal threshold
    below_normal = [(time, available) for time, available in zip(times, availability) if available < normal_threshold]
    if below_normal:
        below_times, below_counts = zip(*below_normal)
        figure.add_trace(go.Scatter(
            x=list(below_times), y=list(below_counts), mode='markers',
            marker=dict(color='#FF6B6B', size=8, symbol='x'),
            name='Below Normal Threshold',
        ))

    figure.update_layout(
        title=f'Machines Available Over Time — {alternative_name}' if alternative_name else 'Machines Available Over Time',
        xaxis_title='Time (years)',
        yaxis_title='Available Machines',
        xaxis=dict(range=[0, period]),
        yaxis=dict(range=[min(availability) - 2, machine_number + 1]),
        hovermode='x unified',
        plot_bgcolor='white',
        xaxis_showgrid=True,
        yaxis_showgrid=True,
    )
    return figure


def plot_availability(
    times,
    availability,
    threshold: int = 36,
    period: int = 15,
    total_machines: int = 45,
    crisis_threshold: int | None = None,
    machine_number: int | None = None,
    replacement_period: int | None = None,
):
    """Chart of the machines available over time, saved in assets/."""
    plt.figure(figsize=(16, 8))

    title = _title_with_alternative("System Availability Over Time", machine_number, replacement_period)

    # Steps, not sloped lines: the count holds until the next event changes it
    plt.step(times, availability, where='post', color='black', linewidth=1, label='Available Machines')
    plt.axhline(y=threshold, color='teal', linestyle='--', linewidth=2,
                label=f'Normal Threshold ({threshold} machines)')
    if crisis_threshold:
        plt.axhline(y=crisis_threshold, color='brown', linestyle='--', linewidth=2,
                    label=f'Crisis Threshold ({crisis_threshold} machines)')

    below_normal = [(time, available) for time, available in zip(times, availability) if available < threshold]
    if below_normal:
        below_times, below_counts = zip(*below_normal)
        plt.scatter(below_times, below_counts, color='#FF6B6B', s=100, zorder=5,
                    label='Below Normal Threshold', marker='x')

    plt.xlabel('Time (years)', fontsize=16)
    plt.ylabel('Available Machines', fontsize=16)
    plt.title(title, fontsize=18, fontweight='bold')
    plt.grid(True, alpha=0.3, axis='y')
    plt.legend(fontsize=14)
    plt.xlim(0, period)

    y_max = (crisis_threshold + 1) if crisis_threshold else (total_machines + 1)
    plt.ylim(24, y_max)
    plt.yticks(range(24, int(y_max) + 1, 2))
    plt.tick_params(axis='both', labelsize=14)

    filepath = _unique_filename('assets', 'availability_timeline', '.png')
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Plot saved as '{filepath}'")


def plot_failures_over_time(
    simulation_key: str = "simulation-1",
    period: int = 15,
    machine_number: int | None = None,
    replacement_period: int | None = None,
):
    """Step chart of the number of failures so far."""
    if simulation_key not in simulations:
        print(f"Simulation '{simulation_key}' not found.")
        return

    events = simulations[simulation_key]
    failure_events = sorted(
        [event for event in events if event.event_type == EventType.FAILURE],
        key=lambda event: event.start_time,
    )
    if not failure_events:
        print(f"No failure events in '{simulation_key}'.")
        return

    times = [0.0] + [float(event.start_time) for event in failure_events] + [period]
    cumulative = list(range(len(failure_events) + 1)) + [len(failure_events)]

    title = _title_with_alternative("Failure Events Over Time", machine_number, replacement_period)

    plt.figure(figsize=(12, 6))
    plt.step(times, cumulative, where='post', linewidth=2, color='black')
    plt.xlabel('Time (years)', fontsize=16)
    plt.ylabel('Cumulative Failures', fontsize=16)
    plt.title(title, fontsize=18, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.xlim(0, period)
    plt.ylim(0, max(cumulative) * 1.1)
    plt.tick_params(axis='both', labelsize=14)
    plt.tight_layout()

    filepath = _unique_filename('assets', 'failure_events_cumulative', '.png')
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Failures plot saved as '{filepath}'")
    return filepath


def plot_failure_rate(
    simulation_key: str = "simulation-1",
    period: int = 15,
    window_size: float = 1.0,
    machine_number: int | None = None,
    replacement_period: int | None = None,
):
    """Failures per year, counted in consecutive windows of `window_size` years."""
    if simulation_key not in simulations:
        print(f"Simulation '{simulation_key}' not found.")
        return

    events = simulations[simulation_key]
    failure_events = [event for event in events if event.event_type == EventType.FAILURE]
    if not failure_events:
        print(f"No failure events in '{simulation_key}'.")
        return

    failure_times = [event.start_time for event in failure_events]
    time_points, rates = [], []
    for window_index in range(int(period / window_size)):
        window_start, window_end = window_index * window_size, (window_index + 1) * window_size
        count = sum(1 for failure_time in failure_times if window_start <= failure_time < window_end)
        time_points.append((window_start + window_end) / 2)
        rates.append(count / window_size)

    average_rate = len(failure_events) / period
    title = _title_with_alternative("Failure Rate Over Time", machine_number, replacement_period)

    plt.figure(figsize=(12, 6))
    plt.plot(time_points, rates, color='black', linewidth=2.5, label='Failure Rate')
    plt.axhline(y=average_rate, color='#2ECC71', linestyle='--', linewidth=2,
                label=f'Average ({average_rate:.2f} failures/year)')
    plt.xlabel('Time (years)', fontsize=16)
    plt.ylabel('Failure Events / Year', fontsize=16)
    plt.title(title, fontsize=18, fontweight='bold')
    plt.grid(True, alpha=0.3, axis='y')
    plt.xlim(0, period)
    plt.ylim(0, max(rates) * 1.2 if rates else 1)
    plt.legend(fontsize=14)
    plt.text(0.98, 0.98, f'Total Failures: {len(failure_events)}',
             transform=plt.gca().transAxes, fontsize=14,
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    plt.tick_params(axis='both', labelsize=14)
    plt.tight_layout()

    filepath = _unique_filename('assets', 'failure_events', '.png')
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Failure rate plot saved as '{filepath}'")
    return filepath


def analyze_failure_rates(simulation_key: str = "simulation-1", period: int = 15):
    """
    Print, per part type, the number of failures the Weibull parameters predict
    (period / MTTF per part) next to the number that happened in the run.
    """
    if simulation_key not in simulations:
        print(f"Simulation '{simulation_key}' not found.")
        return

    events = simulations[simulation_key]
    failure_events = [event for event in events if event.event_type == EventType.FAILURE]
    if not failure_events:
        print(f"No failure events in '{simulation_key}'.")
        return

    failures_by_part: dict = defaultdict(list)
    unique_parts_by_type: dict = defaultdict(set)

    for event in failure_events:
        part = event.maintenance_item
        if part is None:
            continue
        part_type = getattr(part, 'spare_part_type', None)
        part_name = getattr(part, 'name', None)
        eta = getattr(part, 'eta', None)
        beta = getattr(part, 'beta', None)
        if part_type and part_name and eta and beta:
            type_name = part_type.value if hasattr(part_type, 'value') else str(part_type)
            failures_by_part[type_name].append({'eta': eta, 'beta': beta, 'time': event.start_time})
            unique_parts_by_type[type_name].add(part_name)

    print("\n" + "=" * 80)
    print("FAILURE RATE ANALYSIS — Expected vs. Actual")
    print("=" * 80)
    print(f"Simulation: {simulation_key}  |  Period: {period} years\n")
    header = f"{'Part Type':<20} {'Count':<8} {'eta':<8} {'beta':<8} {'MTTF':<8} {'Exp/Part':<10} {'Expected':<10} {'Actual':<10} {'Diff':<10}"
    print(header)
    print("-" * len(header))

    total_expected = total_actual = 0
    for part_type, failure_list in sorted(failures_by_part.items()):
        eta = failure_list[0]['eta']
        beta = failure_list[0]['beta']
        mttf = eta * math.gamma(1 + 1 / beta)
        part_count = len(unique_parts_by_type[part_type])
        expected_per_part = period / mttf
        expected = expected_per_part * part_count
        actual = len(failure_list)
        difference = actual - expected
        total_expected += expected
        total_actual += actual
        print(f"{part_type:<20} {part_count:<8} {eta:<8.2f} {beta:<8.2f} {mttf:<8.2f} "
              f"{expected_per_part:<10.2f} {expected:<10.1f} {actual:<10} {difference:+.1f}")

    print("-" * len(header))
    print(f"{'TOTAL':<20} {'':<8} {'':<8} {'':<8} {'':<8} {'':<10} "
          f"{total_expected:<10.1f} {total_actual:<10} {total_actual - total_expected:+.1f}")

    return failures_by_part


def main(
    total_machines: int = 45,
    threshold: int = 36,
    period: int = 15,
    simulation_key: str = "simulation-1",
    crisis_threshold: int | None = None,
    machine_number: int | None = None,
    replacement_period: int | None = None,
):
    """Compute and plot the availability of one run (used by app.py)."""
    if not simulations:
        print("No simulation data found. Run app.py first.")
        return

    print(f"Found {len(simulations)} simulation(s)")
    times, availability, _ = calculate_availability_timeline(
        simulation_key=simulation_key,
        total_machines=total_machines,
        period=period,
    )
    if times is None:
        return

    plot_availability(
        times, availability,
        threshold=threshold, period=period,
        total_machines=total_machines, crisis_threshold=crisis_threshold,
        machine_number=machine_number, replacement_period=replacement_period,
    )


if __name__ == "__main__":
    main()
