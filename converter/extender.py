import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)


def _infer_weekdays(dates: list[str], reference_end: date) -> frozenset[int]:
    """Return the weekdays the service ran in the 7 days up to reference_end."""
    week_start = reference_end - timedelta(days=6)
    return frozenset(
        date.fromisoformat(d).weekday()
        for d in dates
        if week_start <= date.fromisoformat(d) <= reference_end
    )


def extend_calendar(
    service_dates: dict[str, list[str]],
    feed_end_date: date,
    dt_weekdays: dict[str, frozenset[int]],
    extend_weeks: int,
) -> None:
    """Extend all services by repeat their weekday pattern beyond feed_end_date.

    For each DayType, the weekly pattern is repeated from the day after
    feed_end_date for extend_weeks weeks (no holiday exceptions applied).
    Weekday pattern is taken from dt_weekdays if present, otherwise inferred
    from the service's actual dates in the last 7 days of the feed.
    """
    extension_end = feed_end_date + timedelta(weeks=extend_weeks)
    extended = 0

    for dt_id, dates in service_dates.items():
        weekdays = dt_weekdays.get(dt_id) or _infer_weekdays(dates, feed_end_date)
        if not weekdays:
            continue

        existing = set(dates)
        d = feed_end_date + timedelta(days=1)
        new_dates: list[str] = []
        while d <= extension_end:
            if d.weekday() in weekdays:
                iso = d.isoformat()
                if iso not in existing:
                    new_dates.append(iso)
            d += timedelta(days=1)

        if new_dates:
            service_dates[dt_id] = sorted(existing | set(new_dates))
            extended += 1

    if extended:
        log.info("extend_calendar: extended %d services by %d weeks beyond %s", extended, extend_weeks, feed_end_date)

