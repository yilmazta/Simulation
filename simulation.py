"""SimPy helpers: deterministic polyclinic appointment (schedule) generation.

`config.yml` holds ``arrivals.appointment`` with named schedules and
per-department assignments. Times use ``HH:MM`` 24h strings; the simulation
treats *minute 0* of the first day as **08:00** (clinic open), so
``12:00`` = 4 h from that anchor = 240 SimPy time units, and the next
calendar day starts at +1440 min.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Generator, Iterable, Mapping
from typing import Any, TypeVar

import simpy

MINUTES_PER_DAY = 24 * 60
ANCHOR_8_00 = 8 * 60  # 08:00 in minutes from midnight; offset-from-t0(08:00) = clock - 480

T = TypeVar("T")


def _parse_hhmm(hhmm: str) -> int:
    """Return minutes from midnight (e.g. ``\"13:00\"`` -> 780)."""
    s = str(hhmm).strip()
    h, m = s.split(":", 1)
    return int(h) * 60 + int(m)


def _clock_to_offset_from_8am(hhmm: str) -> int:
    """SimPy time from day start anchor 08:00: first slot of day 0 = 0."""
    return _parse_hhmm(hhmm) - ANCHOR_8_00


def window_slot_offsets(
    start: str,
    end: str,
    interval_minutes: int,
) -> list[int]:
    """All slot offsets (minutes from 08:00) in ``[start, end)`` every ``interval`` min."""

    t0 = _clock_to_offset_from_8am(start)
    t1 = _clock_to_offset_from_8am(end)
    if t1 < t0 or interval_minutes <= 0:
        return []
    out: list[int] = []
    t = t0
    while t < t1 - 1e-9:
        out.append(t)
        t += interval_minutes
    return out


def schedule_windows_to_offsets(
    windows: Iterable[Mapping[str, Any]],
) -> list[int]:
    """Flatten YAML ``windows: [{start, end, interval_minutes}, ...]`` to sorted unique offsets for one day."""

    slots: set[int] = set()
    for w in windows:
        slots.update(
            window_slot_offsets(
                w["start"],
                w["end"],
                int(w["interval_minutes"]),
            )
        )
    return sorted(slots)


def day_slot_times(
    day_index: int,
    windows: Iterable[Mapping[str, Any]],
) -> list[float]:
    """Absolute SimPy time for every appointment slot on ``day_index`` (0 = first day at 08:00 anchor)."""

    base = float(day_index * MINUTES_PER_DAY)
    return [base + t for t in schedule_windows_to_offsets(windows)]


def all_slot_times_n_days(
    n_days: int,
    windows: Iterable[Mapping[str, Any]],
) -> list[float]:
    """``n_days`` worth of schedule slots, monotonically increasing."""
    return sorted(
        t
        for d in range(n_days)
        for t in day_slot_times(d, windows)
    )


def appointment_generator(
    env: simpy.Environment,
    department: str,
    appointment_config: Mapping[str, Any],
    *,
    n_days: int = 1,
    on_arrival: Callable[[str, float], T] | None = None,
) -> Generator[simpy.events.Event, None, T | None]:
    """Drive deterministic arrivals for one department according to ``config['arrivals']['appointment']``.

    Parameters
    ----------
    env
        SimPy environment.
    department
        Key in ``department_schedules`` (e.g. ``\"AdultHipKnee\"``).
    appointment_config
        The value of ``arrivals.appointment`` from ``config.yml`` (``schedules``,
        ``department_schedules``, etc.).
    n_days
        How many 24h calendar days to run (day 0 starts at SimPy 0 = 08:00).
    on_arrival
        If given, called as ``on_arrival(department, env.now)`` when a slot
        time is reached. Otherwise the generator is useful only for
        side-effect-free timing tests.

    The generator:
    1) Resolves the schedule name for this department
    2) Builds the ordered list of all absolute slot times for ``n_days``
    3) Waits with ``timeout`` from current ``env.now`` to each next slot; gaps
       (lunch, overnight) require no code — the timeout simply covers them.

    Yields
    ------
    SimPy timeout events. Returns the last value returned from ``on_arrival``,
    or ``None`` if ``on_arrival`` is omitted.
    """

    dept_map = appointment_config.get("department_schedules") or {}
    schedules = appointment_config.get("schedules") or {}
    if department not in dept_map:
        raise KeyError(f"No schedule assigned for department {department!r} in department_schedules")
    sched_id = str(dept_map[department])
    if sched_id not in schedules:
        raise KeyError(f"Schedule {sched_id!r} not found in appointment.schedules")
    windows = schedules[sched_id].get("windows")
    if not windows:
        raise ValueError(f"Schedule {sched_id!r} has no windows")
    times = all_slot_times_n_days(n_days, windows)
    if not times:
        return on_arrival(department, env.now) if on_arrival else None

    last: T | None = None
    for target in times:
        wait = max(0.0, target - env.now)
        if wait > 0:
            yield env.timeout(wait)
        if on_arrival is not None:
            last = on_arrival(department, env.now)
    return last


# --- Batched multi-department generator (optional) ---------------------------------


def appointment_generators_merged(
    env: simpy.Environment,
    departments: list[str],
    appointment_config: Mapping[str, Any],
    *,
    n_days: int = 1,
    on_arrival: Callable[[str, float], T],
) -> Generator[simpy.events.Event, None, None]:
    """Single timeline merging all department slots, sorted by time (fair merge).

    If two departments share the same slot time, the callback order is
    deterministic (by ``departments`` list order then heap order).
    """

    schedules = appointment_config.get("schedules") or {}
    dept_map = appointment_config.get("department_schedules") or {}
    events: list[tuple[float, int, str]] = []
    for rank, dep in enumerate(departments):
        sid = str(dept_map[dep])
        w = list(schedules[sid]["windows"])
        for t in all_slot_times_n_days(n_days, w):
            heapq.heappush(events, (t, rank, dep))

    while events:
        target, _rank, dep = heapq.heappop(events)
        wait = max(0.0, target - env.now)
        if wait > 0:
            yield env.timeout(wait)
        on_arrival(dep, env.now)
