"""
visualization/timeline.py

Plotly timeline of one simulation run: one row per machine, and every event
drawn as a coloured bar (if it lasts) or marker (if it's instantaneous).
"""
import re
from typing import List, Dict
from collections import defaultdict

import plotly.graph_objects as go

from database import simulations
from classes.event import Event
from classes.event_type import EventType
from db.models import SparePartModel


def natural_sort_key(text):
    """Sort key that puts "Ventilator 2" before "Ventilator 10"."""
    def as_number_or_text(chunk):
        return int(chunk) if chunk.isdigit() else chunk.lower()
    return [as_number_or_text(chunk) for chunk in re.split(r'(\d+)', text)]


def _event_type_label(event_type: EventType) -> str:
    # EventType values are declared as 1-tuples, so unwrap them.
    return event_type.value[0] if isinstance(event_type.value, tuple) else event_type.value


def _chart_title(machine_number, replacement_period, period, alternative_name=None) -> str:
    title = f"Simulation Timeline — {alternative_name}" if alternative_name else "Simulation Timeline"
    if machine_number and replacement_period and period:
        title += (f"<br><sub>({machine_number} machines, "
                  f"replacing every {replacement_period} years, {period} year period)</sub>")
    return title


def event_records(events: List[Event]) -> dict:
    """
    A compact copy of one run's events that can be saved as JSON and turned
    back into the timeline and availability charts later (History page).

    items holds [item name, name of the timeline row] once per item: a part's
    row is its machine. Each event is [type, item index or -1, start, end,
    cost, description]. Times are rounded to 6 decimals (about 30 seconds).
    """
    item_index_by_id: Dict[int, int] = {}
    items: list = []
    records: list = []
    for event in events:
        item = event.maintenance_item
        item_index = -1
        if item is not None:
            item_index = item_index_by_id.get(id(item), -1)
            if item_index == -1:
                if isinstance(item, SparePartModel) and item.machine is not None:
                    row_name = item.machine.name
                else:
                    row_name = item.name
                items.append([getattr(item, "name", str(item)), row_name])
                item_index = len(items) - 1
                item_index_by_id[id(item)] = item_index
        records.append([
            _event_type_label(event.event_type),
            item_index,
            round(event.start_time, 6),
            round(event.end_time, 6),
            round(event.cost or 0.0, 2),
            event.description or "",
        ])
    return {"items": items, "events": records}


def plot_simulation_timeline(
    simulation_key: str = "simulation-1",
    machine_number: int | None = None,
    replacement_period: int | None = None,
    period: int | None = None,
):
    """
    Timeline of the run stored under `simulation_key` in database.simulations.
    machine_number, replacement_period and period only go in the subtitle.
    """
    if simulation_key not in simulations:
        raise ValueError(
            f"Simulation '{simulation_key}' not found. "
            f"Available: {list(simulations.keys())}"
        )

    events: List[Event] = simulations[simulation_key]
    if not events:
        print(f"No events found in {simulation_key}")
        return None
    return plot_timeline_from_records(event_records(events), machine_number, replacement_period, period)


# Colour of each event type on the timeline, in legend order
EVENT_COLORS = {
    _event_type_label(EventType.FAILURE):                '#FF6B6B',
    _event_type_label(EventType.CORRECTIVE_MAINTENANCE): '#4ECDC4',
    _event_type_label(EventType.PREVENTIVE_MAINTENANCE): '#95E1D3',
    _event_type_label(EventType.PURCHASE_REPLACEMENT):   '#FFA07A',
    _event_type_label(EventType.END_OF_MAINTENANCE):     '#A8E6CF',
    _event_type_label(EventType.TO_SERVICE):             '#90EE90',
    _event_type_label(EventType.OUT_OF_SERVICE):         '#FFD93D',
}


def plot_timeline_from_records(
    records: dict,
    machine_number: int | None = None,
    replacement_period: int | None = None,
    period: int | None = None,
    alternative_name: str | None = None,
):
    """The timeline chart from event_records(). The other arguments only go in the title."""
    items = records["items"]
    events = records["events"]
    if not events:
        return None

    # A part's events go on its machine's row
    row_events: Dict[str, list] = defaultdict(list)
    for event in events:
        item_index = event[1]
        if item_index < 0:
            continue
        row_events[items[item_index][1]].append(event)

    machine_names = sorted(row_events.keys(), key=natural_sort_key)

    # All shapes of one event type go into a single trace, separated by None.
    # One trace per type instead of one per event keeps big runs fast.
    shape_x: Dict[str, list] = defaultdict(list)
    shape_y: Dict[str, list] = defaultdict(list)
    shape_hover: Dict[str, list] = defaultdict(list)
    marker_x: Dict[str, list] = defaultdict(list)
    marker_y: Dict[str, list] = defaultdict(list)
    marker_hover: Dict[str, list] = defaultdict(list)

    for row_index, machine_name in enumerate(machine_names):
        machine_event_list = sorted(row_events[machine_name], key=lambda machine_event: machine_event[2])

        for event_label, _, start_time, end_time, cost, description in machine_event_list:
            label = description or "Unknown Event"
            cost_line = f"Cost: ${cost:.2f}<br>" if cost and cost > 0 else ""
            duration = end_time - start_time

            if duration < 0.0001:
                hover = (
                    f"<b>{label}</b><br>Event: {event_label}<br>"
                    f"Time: {start_time:.4f} years<br>{cost_line}<extra></extra>"
                )
                # A short vertical line, plus a marker for the hover
                shape_x[event_label].extend([start_time, start_time, None])
                shape_y[event_label].extend([row_index - 0.3, row_index + 0.3, None])
                shape_hover[event_label].extend([hover, hover, None])
                marker_x[event_label].append(start_time)
                marker_y[event_label].append(row_index)
                marker_hover[event_label].append(hover)
            else:
                hover = (
                    f"<b>{label}</b><br>Event: {event_label}<br>"
                    f"Start: {start_time:.4f} years<br>"
                    f"End: {end_time:.4f} years<br>"
                    f"Duration: {duration:.4f} years<br>{cost_line}<extra></extra>"
                )
                # A filled rectangle, drawn as a closed outline
                shape_x[event_label].extend([
                    start_time, end_time, end_time,
                    start_time, start_time, None,
                ])
                shape_y[event_label].extend([
                    row_index - 0.4, row_index - 0.4, row_index + 0.4,
                    row_index + 0.4, row_index - 0.4, None,
                ])
                shape_hover[event_label].extend([hover, hover, hover, hover, hover, None])
                center = (start_time + end_time) / 2
                marker_x[event_label].append(center)
                marker_y[event_label].append(row_index)
                marker_hover[event_label].append(hover)

    figure = go.Figure()

    for event_label, color in EVENT_COLORS.items():
        if shape_x[event_label]:
            figure.add_trace(go.Scatter(
                x=shape_x[event_label], y=shape_y[event_label],
                fill='toself', fillcolor=color, line=dict(color=color, width=1),
                mode='lines', name=event_label, legendgroup=event_label, showlegend=False,
                hovertemplate=shape_hover[event_label], hoverinfo='skip',
            ))
        if marker_x[event_label]:
            figure.add_trace(go.Scatter(
                x=marker_x[event_label], y=marker_y[event_label], mode='markers',
                marker=dict(size=8, color=color, symbol='circle',
                            line=dict(color='white', width=1)),
                name=event_label, legendgroup=event_label, showlegend=False,
                hovertemplate=marker_hover[event_label],
            ))

    # A dashed line at every year
    max_time = max(event[3] for event in events)
    for year in range(int(max_time) + 2):
        figure.add_vline(x=year, line=dict(color="gray", width=1, dash="dash"),
                         opacity=0.5, layer="below")

    # Legend entries (the traces above are hidden from the legend)
    for event_label, color in EVENT_COLORS.items():
        figure.add_trace(go.Scatter(
            x=[None], y=[None], mode='markers',
            marker=dict(size=10, color=color),
            name=event_label, legendgroup=event_label, showlegend=True,
        ))

    figure.update_layout(
        title=_chart_title(machine_number, replacement_period, period, alternative_name),
        xaxis_title="Time (Years)",
        yaxis=dict(
            tickmode='array',
            tickvals=list(range(len(machine_names))),
            ticktext=machine_names,
            autorange='reversed',
        ),
        hovermode='closest',
        height=max(600, len(machine_names) * 25),
        showlegend=True,
        legend=dict(title="Event Types", yanchor="top", y=0.99,
                    xanchor="left", x=1.01),
        plot_bgcolor='white',
        xaxis=dict(showgrid=True, gridcolor='lightgray', gridwidth=0.5),
        yaxis_showgrid=True,
    )
    return figure
