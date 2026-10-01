import math
import random
from typing import Iterable, TypeVar, Any, Optional, List
from classes import EventType

ItemType = TypeVar("ItemType")


def find_obj_by_attr(
    items: Iterable[ItemType],
    attr_name: str,
    attr_value: Any,
    default: Optional[ItemType] = None,
) -> Optional[ItemType]:
    """First item whose attribute `attr_name` equals `attr_value`, else `default`."""
    missing = object()
    for item in items:
        item_value = getattr(item, attr_name, missing)
        if item_value is attr_value or item_value == attr_value:
            return item
    return default


def find_all_by_attr(
    items: Iterable[ItemType],
    attr_name: str,
    attr_value: Any,
) -> List[ItemType]:
    """Every item whose attribute `attr_name` equals `attr_value`."""
    missing = object()
    return [
        item
        for item in items
        if getattr(item, attr_name, missing) == attr_value
    ]


def weibull_residual_life(current_age, beta, eta):
    """Random remaining life of a Weibull item that has already survived to `current_age`."""
    if current_age < 0:
        current_age = 0

    # Uniform draw, kept strictly inside (0, 1) so the log below is defined
    uniform_draw = random.random()
    if uniform_draw <= 0.0:
        uniform_draw = 1e-16
    if uniform_draw >= 1.0:
        uniform_draw = 1.0 - 1e-16

    # Cumulative hazard reached so far: H(t) = (t / eta) ^ beta
    hazard_at_age = (current_age / eta) ** beta

    # Standard exponential draw by inverse CDF. log1p(-u) is more accurate than
    # log(1 - u) when u is close to 0, which matters for long lives.
    exponential_draw = -math.log1p(-uniform_draw)

    # The next failure happens at the age where H reaches hazard_at_age + exponential_draw
    failure_age = eta * (hazard_at_age + exponential_draw) ** (1.0 / beta)

    residual_time = failure_age - current_age
    return residual_time if residual_time > 0.0 else 1e-12


def ceil_from_list(values, lower_bound):
    """Smallest value that is >= lower_bound, or None if there is none."""
    candidates = [value for value in values if value >= lower_bound]
    return min(candidates) if candidates else None


class ShiftSchedule:
    """
    Weekly table of operating time for a machine that always works the same
    shift, on a fixed set of weekdays.

    Everything is in years, like eta, beta and runtime, so the wear clock and
    the calendar clock can be compared directly. HOURS_PER_YEAR is exactly
    24 * DAYS_PER_YEAR (not the 8760 used for repair times elsewhere) so that a
    24 h, 7 days a week schedule gives wear_age == runtime exactly. That is why
    "continuous use" needs no separate code: it is just this schedule.

    The schedule repeats every 7 days, so the operating time up to day t is
    floor(t / 7) * weekly_total + cum_within_week[t mod 7]. Converting in either
    direction is one division plus a lookup in a table of at most 7 rows.
    The maths are in plans/shift-mode-methodology.md.
    """

    DAYS_PER_YEAR = 365.25
    HOURS_PER_YEAR = 24.0 * DAYS_PER_YEAR

    def __init__(self, shift_hours: float, session_days: list[int] | None = None):
        active_days = set(session_days) if session_days is not None else set(range(7))
        daily_years = shift_hours / self.HOURS_PER_YEAR
        self.daily_wear: list[float] = [daily_years if weekday in active_days else 0.0 for weekday in range(7)]
        self.cum_within_week: list[float] = []
        running_total = 0.0
        for day_wear in self.daily_wear:
            running_total += day_wear
            self.cum_within_week.append(running_total)
        self.weekly_total: float = self.cum_within_week[-1]

    def to_calendar_offset(self, residual_wear_years: float) -> float:
        """Calendar years needed to accumulate `residual_wear_years` of operating time."""
        if self.weekly_total <= 0:
            return float("inf")

        full_weeks, remainder = divmod(residual_wear_years, self.weekly_total)
        day_in_week = 6
        previous_cumulative = self.cum_within_week[5]
        for weekday in range(7):
            if self.cum_within_week[weekday] >= remainder:
                day_in_week = weekday
                previous_cumulative = self.cum_within_week[weekday - 1] if weekday > 0 else 0.0
                break

        wear_into_day = remainder - previous_cumulative
        fraction_of_day = wear_into_day / self.daily_wear[day_in_week] if self.daily_wear[day_in_week] > 0 else 0.0
        calendar_days = full_weeks * 7 + day_in_week + fraction_of_day
        return calendar_days / self.DAYS_PER_YEAR

    def wear_accrued(self, elapsed_years: float) -> float:
        """Operating time (in years) accumulated over `elapsed_years` of calendar time."""
        elapsed_days = elapsed_years * self.DAYS_PER_YEAR
        full_weeks, remainder_days = divmod(elapsed_days, 7)
        whole_days = int(remainder_days)
        partial_day_fraction = remainder_days - whole_days

        wear = full_weeks * self.weekly_total
        wear += self.cum_within_week[whole_days - 1] if whole_days > 0 else 0.0
        if whole_days < 7:
            wear += self.daily_wear[whole_days] * partial_day_fraction
        return wear


def unit_name(item) -> str:
    """
    The machine an event counts against. A failed part takes its machine out
    of service, and the failure is logged on the part as well as on the
    machine, so both must count as the same unit, not as two machines down.
    """
    machine = getattr(item, "machine", None)
    if machine is not None and hasattr(item, "spare_part_type"):
        return machine.name
    return getattr(item, "name", str(item))


def _out_of_service_intervals(events) -> list[tuple[str, float, float]]:
    """(machine name, start, end) of every OUT_OF_SERVICE event with a duration."""
    intervals: list[tuple[str, float, float]] = []
    for event in events:
        if event.event_type == EventType.OUT_OF_SERVICE:
            if event.maintenance_item and event.end_time > event.start_time:
                intervals.append((unit_name(event.maintenance_item), event.start_time, event.end_time))
    return intervals


def calculate_session_availability(
    events,
    total_machines: int,
    threshold: int,
    period: float,
    session_days: list[int] | None = None,
    shift_durations: list[float] | None = None,
) -> float:
    """
    Fleet availability: at the start of every shift, min(available, threshold) / threshold,
    averaged over the whole horizon.

    `threshold` is the headcount that counts as 100 %, not a pass/fail limit,
    so a fleet smaller than the threshold still gets partial credit (38
    machines against a crisis target of 44 averages about 86 %, not 0 %).

    session_days are the weekdays with sessions (0 = Monday, and Monday to
    Saturday if not given). shift_durations are the shift lengths in hours,
    back to back from midnight: [8, 8] means shifts starting at 0 h and 8 h.
    """
    if session_days is None:
        session_days = [0, 1, 2, 3, 4, 5]
    if shift_durations is None:
        shift_durations = [8.0, 8.0]

    session_day_set = set(session_days)
    shift_start_offsets_years = []
    cumulative_hours = 0.0
    for duration in shift_durations:
        shift_start_offsets_years.append(cumulative_hours / 8760.0)
        cumulative_hours += duration

    # OUT_OF_SERVICE is the only downtime signal. Every gap that takes a unit
    # out of use (repair, uncovered PM, waiting for a redirected unit) has one.
    out_of_service = _out_of_service_intervals(events)

    # Start time (in years) of every shift in the horizon
    checkpoints: list[float] = []
    day = 0
    while True:
        day_start = day / 365.25
        if day_start >= period:
            break
        weekday = day % 7
        if weekday in session_day_set:
            for offset in shift_start_offsets_years:
                checkpoint = day_start + offset
                if checkpoint < period:
                    checkpoints.append(checkpoint)
        day += 1

    if not checkpoints:
        return 0.0

    if threshold <= 0:
        return 1.0

    total_ratio = 0.0
    for checkpoint in checkpoints:
        # Distinct units out of service at this moment
        units_down: set[str] = set()
        for name, start, end in out_of_service:
            if start <= checkpoint < end:
                units_down.add(name)
        available = total_machines - len(units_down)
        total_ratio += min(available, threshold) / threshold

    return total_ratio / len(checkpoints)


def calculate_session_hours(
    events,
    total_machines: int,
    threshold: int,
    period: float,
    session_days: list[int] | None = None,
    shift_durations: list[float] | None = None,
) -> dict[str, float]:
    """
    Same checkpoints as calculate_session_availability, counted in hours:
    for every shift, the available machines (at most `threshold`) times the
    shift length, against the hours if all `threshold` places had been filled.
    """
    if session_days is None:
        session_days = [0, 1, 2, 3, 4, 5]
    if shift_durations is None:
        shift_durations = [8.0, 8.0]

    session_day_set = set(session_days)
    shift_starts: list[tuple[float, float]] = []  # (offset in years, duration in hours)
    cumulative_hours = 0.0
    for duration in shift_durations:
        shift_starts.append((cumulative_hours / 8760.0, duration))
        cumulative_hours += duration

    out_of_service = _out_of_service_intervals(events)

    scheduled_hours = 0.0
    worked_hours = 0.0

    day = 0
    while True:
        day_start = day / 365.25
        if day_start >= period:
            break
        weekday = day % 7
        if weekday in session_day_set:
            for offset, duration in shift_starts:
                checkpoint = day_start + offset
                if checkpoint >= period:
                    continue
                scheduled_hours += threshold * duration

                units_down: set[str] = set()
                for name, start, end in out_of_service:
                    if start <= checkpoint < end:
                        units_down.add(name)
                available = total_machines - len(units_down)
                worked_hours += min(available, threshold) * duration
        day += 1

    return {
        "scheduled_hours": scheduled_hours,
        "worked_hours": worked_hours,
        "lost_hours": scheduled_hours - worked_hours,
    }


# Keys returned by calculate_resilience_metrics, in display order.
RESILIENCE_METRICS: tuple[str, ...] = (
    "crisis_expected_unmet",
)


def calculate_resilience_metrics(
    events,
    total_machines: int,
    threshold: int,
    period: float,
) -> dict[str, float]:
    """
    Crisis resilience of one replication, against `threshold` (the crisis
    target). Unlike calculate_session_availability, which looks at the fleet
    at the start of each shift, this follows the number of working units
    continuously over [0, period) and assumes the crisis demand is there the
    whole time (a sustained surge).

    Downtime comes from the OUT_OF_SERVICE events, one unit per machine (a
    part's downtime is its machine's), with overlapping periods of the same
    machine counted once.

    crisis_expected_unmet is the time average of max(0, target - available),
    in number of units.
    """
    if period <= 0 or threshold <= 0:
        return {"crisis_expected_unmet": 0.0}

    # Merge the downtime periods of each unit so that overlapping records
    # (for example a repair and a redirect wait) count as one unit down.
    periods_by_unit: dict[str, list[tuple[float, float]]] = {}
    for event in events:
        if event.event_type == EventType.OUT_OF_SERVICE and event.maintenance_item:
            start, end = max(event.start_time, 0.0), min(event.end_time, period)
            if end > start:
                periods_by_unit.setdefault(unit_name(event.maintenance_item), []).append((start, end))

    # +1 / -1 change in available units at each start and end time
    changes: dict[float, int] = {}
    for unit_periods in periods_by_unit.values():
        unit_periods.sort()
        current_start, current_end = unit_periods[0]
        merged: list[tuple[float, float]] = []
        for start, end in unit_periods[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                merged.append((current_start, current_end))
                current_start, current_end = start, end
        merged.append((current_start, current_end))
        for start, end in merged:
            changes[start] = changes.get(start, 0) - 1
            changes[end] = changes.get(end, 0) + 1

    times = sorted({0.0, period, *changes})
    available = total_machines
    unmet_integral = 0.0
    for segment_start, segment_end in zip(times, times[1:]):
        available += changes.get(segment_start, 0)
        if available < threshold:
            unmet_integral += (segment_end - segment_start) * (threshold - available)

    return {"crisis_expected_unmet": unmet_integral / period}
