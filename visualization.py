import plotly.graph_objects as go
import plotly.express as px
from typing import List, Dict, Optional
from database import simulations
from classes.event import Event
from classes.event_type import EventType
from db.models.spare_part import SparePartModel as SparePart
from collections import defaultdict
import re


def natural_sort_key(text):
    """
    Sort key for natural/alphanumeric sorting.
    Converts 'Ventilator10' to come after 'Ventilator2'.
    """
    def atoi(text):
        return int(text) if text.isdigit() else text.lower()
    return [atoi(c) for c in re.split(r'(\d+)', text)]


def plot_simulation_timeline(simulation_key: str = "simulation-1", machine_number: Optional[int] = None, replacement_period: Optional[int] = None, period: Optional[int] = None) -> Optional[go.Figure]:
    """
    Creates an interactive timeline visualization of a simulation showing all machines and their events.

    Args:
        simulation_key: Key of the simulation in the simulations dictionary (e.g., "simulation-1")
        machine_number: Number of machines in the alternative
        replacement_period: Replacement period in years
        period: Total simulation period in years
    """

    # Get events from the simulation
    if simulation_key not in simulations:
        raise ValueError(f"Simulation '{simulation_key}' not found in database. Available: {list(simulations.keys())}")

    events: List[Event] = simulations[simulation_key]

    if not events:
        print(f"No events found in {simulation_key}")
        return

    # Group events by machine (including part events under their parent machine)
    machine_events: Dict[str, List[Event]] = defaultdict(list)
    for event in events:
        item = event.maintenance_item
        if item == None:
            continue
        # If it's a part, use the parent machine name, otherwise use the item name
        if isinstance(item, SparePart) and item.machine != None:
            machine_name = f"{item.machine.name}"
        else:
            machine_name = f"{item.name}"
        machine_events[machine_name].append(event)

    # Sort machines by name using natural sort (Ventilator1, Ventilator2, ..., Ventilator10)
    machine_names = sorted(machine_events.keys(), key=natural_sort_key)

    # Define colors for each event type
    event_colors = {
        EventType.FAILURE: '#FF6B6B',                    # Red
        EventType.CORRECTIVE_MAINTENANCE: '#4ECDC4',     # Teal
        EventType.PREVENTIVE_MAINTENANCE: '#95E1D3',     # Light teal
        EventType.PURCHASE_REPLACEMENT: '#FFA07A',       # Light salmon
        EventType.END_OF_MAINTENANCE: '#A8E6CF',         # Light green
        EventType.TO_SERVICE: '#90EE90',                 # Light green
        EventType.OUT_OF_SERVICE: '#FFD93D',             # Yellow
    }

    # Create figure
    fig = go.Figure()

    # Add traces for each machine and event
    for machine_idx, machine_name in enumerate(machine_names):
        machine_event_list = machine_events[machine_name]

        # Sort events by start time
        machine_event_list.sort(key=lambda e: e.start_time)

        for event in machine_event_list:
            # Use event description directly
            component_label = event.description if event.description else "Unknown Event"

            event_type_str = event.event_type.value[0] if isinstance(event.event_type.value, tuple) else event.event_type.value
            color = event_colors.get(event.event_type, '#95A5A6')

            # Build hover template with conditional cost display
            cost_line = f"Cost: ${event.cost:.2f}<br>" if event.cost and event.cost > 0 else ""

            # Determine if event is momentary (no duration) or has duration
            is_momentary = event.duration < 0.0001  # Very small threshold

            if is_momentary:
                # Add as a vertical line/marker
                hover_text = (
                    f"<b>{component_label}</b><br>"
                    f"Event: {event_type_str}<br>"
                    f"Time: {event.start_time:.4f} years<br>"
                    f"{cost_line}"
                    "<extra></extra>"
                )
                # Add vertical line
                fig.add_trace(go.Scatter(
                    x=[event.start_time, event.start_time],
                    y=[machine_idx - 0.3, machine_idx + 0.3],
                    mode='lines',
                    line=dict(color=color, width=3),
                    name=event_type_str,
                    legendgroup=event_type_str,
                    showlegend=False,
                    hoverinfo='skip',
                ))
                # Add single marker at center
                fig.add_trace(go.Scatter(
                    x=[event.start_time],
                    y=[machine_idx],
                    mode='markers',
                    marker=dict(size=10, color=color, symbol='diamond', line=dict(color='white', width=1)),
                    name=event_type_str,
                    legendgroup=event_type_str,
                    showlegend=False,
                    hovertemplate=hover_text,
                ))
            else:
                # Add as a bar with duration
                hover_text = (
                    f"<b>{component_label}</b><br>"
                    f"Event: {event_type_str}<br>"
                    f"Start: {event.start_time:.4f} years<br>"
                    f"End: {event.end_time:.4f} years<br>"
                    f"Duration: {event.duration:.4f} years<br>"
                    f"{cost_line}"
                    "<extra></extra>"
                )
                # Add the bar (filled polygon)
                fig.add_trace(go.Scatter(
                    x=[event.start_time, event.end_time, event.end_time, event.start_time, event.start_time],
                    y=[machine_idx - 0.4, machine_idx - 0.4, machine_idx + 0.4, machine_idx + 0.4, machine_idx - 0.4],
                    fill='toself',
                    fillcolor=color,
                    line=dict(color=color, width=1),
                    mode='lines',
                    name=event_type_str,
                    legendgroup=event_type_str,
                    showlegend=False,
                    hovertemplate=hover_text,
                ))
                # Add a marker at the center for easier hovering
                center_time = (event.start_time + event.end_time) / 2
                fig.add_trace(go.Scatter(
                    x=[center_time],
                    y=[machine_idx],
                    mode='markers',
                    marker=dict(size=8, color=color, symbol='circle', line=dict(color='white', width=1)),
                    name=event_type_str,
                    legendgroup=event_type_str,
                    showlegend=False,
                    hovertemplate=hover_text,
                ))

    # Add vertical lines for each year
    # Determine the maximum time from events
    max_time = max(event.end_time for event in events)
    num_years = int(max_time) + 1  # Round up to include the last year

    for year in range(num_years + 1):
        fig.add_vline(
            x=year,
            line=dict(color="gray", width=1, dash="dash"),
            opacity=0.5,
            layer="below"
        )

    # Add legend manually
    for event_type, color in event_colors.items():
        event_type_str = event_type.value[0] if isinstance(event_type.value, tuple) else event_type.value
        fig.add_trace(go.Scatter(
            x=[None],
            y=[None],
            mode='markers',
            marker=dict(size=10, color=color),
            name=event_type_str,
            legendgroup=event_type_str,
            showlegend=True,
        ))

    # Build title with alternative info
    title = f"Simulation Timeline"
    if machine_number is not None and replacement_period is not None and period is not None:
        title += f"<br><sub>({machine_number} machines, replacing every {replacement_period} years, {period} year period)</sub>"

    # Update layout
    fig.update_layout(
        title=title,
        xaxis_title="Time (Years)",
        yaxis_title="Machines",
        yaxis=dict(
            tickmode='array',
            tickvals=list(range(len(machine_names))),
            ticktext=machine_names,
            autorange='reversed',  # Top to bottom
        ),
        hovermode='closest',
        height=max(600, len(machine_names) * 25),  # Adjust height based on number of machines
        showlegend=True,
        legend=dict(
            title="Event Types",
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=1.01
        ),
        plot_bgcolor='white',
        xaxis=dict(
            showgrid=True,
            gridcolor='lightgray',
            gridwidth=0.5,
        ),
        yaxis_showgrid=True,
    )

    return fig


def plot_simulation_timeline_gantt(simulation_key: str = "simulation-1", machine_number: Optional[int] = None, replacement_period: Optional[int] = None, period: Optional[int] = None) -> Optional[go.Figure]:
    """
    Alternative visualization using Plotly's built-in Gantt chart for duration events.
    Momentary events are shown as scatter markers.

    Args:
        simulation_key: Key of the simulation in the simulations dictionary
        machine_number: Number of machines in the alternative
        replacement_period: Replacement period in years
        period: Total simulation period in years
    """

    # Get events from the simulation
    if simulation_key not in simulations:
        raise ValueError(f"Simulation '{simulation_key}' not found in database. Available: {list(simulations.keys())}")

    events: List[Event] = simulations[simulation_key]

    if not events:
        print(f"No events found in {simulation_key}")
        return

    # Prepare data for Gantt chart
    gantt_data = []
    marker_data = []

    for event in events:

        event_type_str = event.event_type.value[0] if isinstance(event.event_type.value, tuple) else event.event_type.value
        event_description = event.description if event.description else "Unknown Event"

        # Check if momentary or duration
        is_momentary = event.duration < 0.0001

        if is_momentary:
            marker_data.append({
                'Description': event_description,
                'Time': event.start_time,
                'Event': event_type_str,
                'Cost': event.cost,
            })
        else:
            gantt_data.append({
                'Description': event_description,
                'Start': event.start_time,
                'Finish': event.end_time,
                'Event': event_type_str,
                'Duration': event.duration,
                'Cost': event.cost,
            })

    # Build title with alternative info
    title = f"Simulation Timeline "
    if machine_number is not None and replacement_period is not None and period is not None:
        title += f"<br><sub>({machine_number} machines, replacing every {replacement_period} years, {period} year period)</sub>"

    # Create figure with Plotly Express timeline
    if gantt_data:
        fig = px.timeline(
            gantt_data,
            x_start="Start",
            x_end="Finish",
            y="Machine",
            color="Event",
            hover_data=["Description", "Duration", "Cost"],
            title=title
        )

        # Update hover template - show description and conditionally show cost
        fig.update_traces(
            hovertemplate="<b>%{customdata[0]}</b><br>Event: %{fullData.name}<br>Duration: %{customdata[1]:.4f} years<br>Cost: $%{customdata[2]:.2f}<extra></extra>"
        )
    else:
        fig = go.Figure()
        fig.update_layout(title=title)

    # Add momentary events as markers
    if marker_data:
        # Get unique machines for y-axis positioning (using natural sort)
        machines = sorted(list(set([d['Machine'] for d in gantt_data + marker_data])), key=natural_sort_key)
        machine_to_idx = {m: i for i, m in enumerate(machines)}

        for marker in marker_data:
            # Conditional cost display
            cost_line = f"Cost: ${marker['Cost']:.2f}<br>" if marker['Cost'] and marker['Cost'] > 0 else ""

            fig.add_trace(go.Scatter(
                x=[marker['Time']],
                y=[marker['Machine']],
                mode='markers',
                marker=dict(
                    symbol='line-ns-open',
                    size=15,
                    line=dict(width=3),
                ),
                name=marker['Event'],
                hovertemplate=(
                    f"<b>{marker['Description']}</b><br>"
                    f"Event: {marker['Event']}<br>"
                    f"Time: {marker['Time']:.4f} years<br>"
                    f"{cost_line}"
                    "<extra></extra>"
                ),
            ))

    # Add vertical lines for each year
    if events:
        max_time = max(event.end_time for event in events)
        num_years = int(max_time) + 1

        for year in range(num_years + 1):
            fig.add_vline(
                x=year,
                line=dict(color="gray", width=1, dash="dash"),
                opacity=0.5,
                layer="below"
            )

    fig.update_layout(
        xaxis_title="Time (Years)",
        yaxis_title="Machines",
        height=max(600, len(set([e['Machine'] for e in gantt_data + marker_data])) * 30),
    )

    return fig


if __name__ == "__main__":
    # Example usage
    from classes.alternative import Alternative

    # Create an alternative to generate simulation data
    print("Creating simulation...")
    alt = Alternative(name="simulation-1", machine_number=38, replacement_period=9, period=15, simulation_number=1)

    print("\nGenerating timeline visualization...")
    # Create the visualization
    fig = plot_simulation_timeline("simulation-1")

    # Show the plot
    if fig:
        fig.show()

    # Alternative Gantt-style visualization
    # fig2 = plot_simulation_timeline_gantt("simulation-1")
    # fig2.show()
