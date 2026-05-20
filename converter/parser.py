import io
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Optional

NS = "http://www.netex.org.uk/netex"

_DOW_MAP = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}

log = logging.getLogger(__name__)


def _t(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _txt(el, tag: str, default: str = "") -> str:
    child = el.find(_t(tag))
    if child is None or not child.text:
        return default
    return child.text.strip().replace("�", "")


def _load_xml(xml_path: str) -> ET.Element:
    """Parse XML with encoding fallback for files that declare UTF-8 but contain Latin-1 bytes."""
    with open(xml_path, "rb") as f:
        raw = f.read()
    try:
        return ET.parse(io.BytesIO(raw)).getroot()
    except ET.ParseError:
        # File declares UTF-8 but has raw Latin-1/Windows-1252 bytes → re-parse as Latin-1
        log.warning("UTF-8 parse failed, retrying as Latin-1")
        text = raw.decode("latin-1")
        text = re.sub(r"<\?xml.*?\?>", "", text, count=1)
        return ET.fromstring(text.encode("utf-8"))


def parse(xml_path: str, extend_calendar_weeks: int = 0) -> dict:
    log.info("Parsing %s", xml_path)
    root = _load_xml(xml_path)

    agencies = _parse_agencies(root)
    stops, ssp_to_stop = _parse_stops(root)
    routes = _parse_routes(root)
    service_dates, feed_end_date, dt_weekdays, dt_op_ends = _parse_calendar(root)
    # if extend_calendar_weeks > 0 and feed_end_date is not None:
    #     _extend_calendar(service_dates, feed_end_date, dt_weekdays, dt_op_ends, extend_calendar_weeks)
    patterns, spijp_to_ssp, pattern_to_line = _parse_journey_patterns(root)
    trips, stop_times = _parse_timetable(root, patterns, pattern_to_line, ssp_to_stop)

    feed_info = _parse_feed_info(root, agencies, service_dates)

    log.info(
        "Parsed: %d agencies, %d stops, %d routes, %d services, %d trips, %d stop_times",
        len(agencies),
        len(stops),
        len(routes),
        len(service_dates),
        len(trips),
        len(stop_times),
    )
    return {
        "agency": agencies,
        "stops": stops,
        "routes": routes,
        "service_dates": service_dates,
        "trips": trips,
        "stop_times": stop_times,
        "feed_info": feed_info,
    }


# ---------------------------------------------------------------------------
# Feed info
# ---------------------------------------------------------------------------

def _parse_feed_info(root, agencies: list[dict], service_dates: dict[str, list[str]]) -> list[dict]:
    publisher_name = agencies[0]["agency_name"] if agencies else ""
    publisher_url = agencies[0]["agency_url"] if agencies else ""
    lang = agencies[0].get("agency_lang", "it") if agencies else "it"

    version = ""
    ts_el = root.find(_t("PublicationTimestamp"))
    if ts_el is not None and ts_el.text:
        version = ts_el.text.strip()[:10].replace("-", "")

    all_dates = [d for dates in service_dates.values() for d in dates]
    feed_start_date = min(all_dates).replace("-", "") if all_dates else ""
    feed_end_date = max(all_dates).replace("-", "") if all_dates else ""

    return [
        {
            "feed_publisher_name": publisher_name,
            "feed_publisher_url": publisher_url,
            "feed_lang": lang,
            "feed_start_date": feed_start_date,
            "feed_end_date": feed_end_date,
            "feed_version": version,
        }
    ]


# ---------------------------------------------------------------------------
# Agency
# ---------------------------------------------------------------------------

def _parse_agencies(root) -> list[dict]:
    agencies = []
    for op in root.iter(_t("Operator")):
        contact = op.find(_t("ContactDetails"))
        url = _txt(contact, "Url") if contact is not None else ""
        phone = _txt(contact, "Phone") if contact is not None else ""
        agencies.append(
            {
                "agency_id": op.get("id"),
                "agency_name": _txt(op, "Name"),
                "agency_url": url or "https://www.atv.verona.it",
                "agency_timezone": "Europe/Rome",
                "agency_lang": "it",
                "agency_phone": phone,
            }
        )
    return agencies


# ---------------------------------------------------------------------------
# Stops
# ---------------------------------------------------------------------------

def _parse_stops(root) -> tuple[list[dict], dict[str, str]]:
    stops = []
    for sp in root.iter(_t("StopPlace")):
        centroid = sp.find(_t("Centroid"))
        if centroid is None:
            continue
        loc = centroid.find(_t("Location"))
        if loc is None:
            continue
        lat_el = loc.find(_t("Latitude"))
        lon_el = loc.find(_t("Longitude"))
        if lat_el is None or lon_el is None:
            continue
        stops.append(
            {
                "stop_id": sp.get("id"),
                "stop_name": _txt(sp, "Name"),
                "stop_lat": lat_el.text.strip(),
                "stop_lon": lon_el.text.strip(),
            }
        )

    # ScheduledStopPoint id → StopPlace id
    ssp_to_stop: dict[str, str] = {}
    for psa in root.iter(_t("PassengerStopAssignment")):
        ssp_ref = psa.find(_t("ScheduledStopPointRef"))
        sp_ref = psa.find(_t("StopPlaceRef"))
        if ssp_ref is not None and sp_ref is not None:
            ssp_to_stop[ssp_ref.get("ref")] = sp_ref.get("ref")

    return stops, ssp_to_stop


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_TRANSPORT_TYPE = {
    "bus": 3,
    "coach": 3,
    "tram": 0,
    "metro": 1,
    "rail": 2,
    "ferry": 4,
}


def _parse_routes(root) -> list[dict]:
    routes = []
    for line in root.iter(_t("Line")):
        op_ref = line.find(_t("OperatorRef"))
        mode = _txt(line, "TransportMode", "bus").lower()
        routes.append(
            {
                "route_id": line.get("id"),
                "agency_id": op_ref.get("ref") if op_ref is not None else "",
                "route_short_name": _txt(line, "ShortName") or _txt(line, "PublicCode"),
                "route_long_name": _txt(line, "Name"),
                "route_type": str(_TRANSPORT_TYPE.get(mode, 3)),
                "route_desc": _txt(line, "Description"),
            }
        )
    return routes


# ---------------------------------------------------------------------------
# Calendar  (UicOperatingPeriod ValidDayBits → calendar_dates)
# ---------------------------------------------------------------------------

def _parse_calendar(
    root,
) -> tuple[dict[str, list[str]], Optional[date], dict[str, frozenset[int]], dict[str, date]]:
    """Return (service_dates, feed_end_date, dt_weekdays, dt_op_ends).

    dt_weekdays maps DayType id → frozenset of ISO weekday ints (0=Mon … 6=Sun).
    dt_op_ends  maps DayType id → max UicOperatingPeriod ToDate for that DayType.
    feed_end_date is ServiceCalendar.ToDate if present, else max op ToDate.
    """
    # UicOperatingPeriod id → (active dates, ToDate)
    periods: dict[str, list[str]] = {}
    op_end: dict[str, date] = {}
    for uop in root.iter(_t("UicOperatingPeriod")):
        op_id = uop.get("id")
        from_str = _txt(uop, "FromDate")[:10]
        bits = _txt(uop, "ValidDayBits")
        from_date = date.fromisoformat(from_str)
        periods[op_id] = [
            (from_date + timedelta(days=i)).isoformat()
            for i, bit in enumerate(bits)
            if bit == "1"
        ]
        to_str = _txt(uop, "ToDate")
        if to_str:
            op_end[op_id] = date.fromisoformat(to_str[:10])

    # DayType id → weekday set (from PropertyOfDay/DaysOfWeek)
    dt_weekdays: dict[str, frozenset[int]] = {}
    for dt in root.iter(_t("DayType")):
        dow_el = dt.find(f".//{_t('DaysOfWeek')}")
        if dow_el is None or not dow_el.text:
            continue
        days = frozenset(_DOW_MAP[d] for d in dow_el.text.split() if d in _DOW_MAP)
        if days:
            dt_weekdays[dt.get("id")] = days

    # DayTypeAssignment → DayType id → list of UicOperatingPeriod ids
    dt_to_ops: dict[str, list[str]] = {}
    for dta in root.iter(_t("DayTypeAssignment")):
        dt_ref = dta.find(_t("DayTypeRef"))
        op_ref = dta.find(_t("OperatingPeriodRef"))
        if dt_ref is None or op_ref is None:
            continue
        dt_to_ops.setdefault(dt_ref.get("ref"), []).append(op_ref.get("ref"))

    # service_id (= DayType id) → sorted unique active dates
    service_dates = {
        dt_id: sorted({d for op_id in op_ids for d in periods.get(op_id, [])})
        for dt_id, op_ids in dt_to_ops.items()
    }

    # Max UicOperatingPeriod.ToDate per DayType
    dt_op_ends: dict[str, date] = {
        dt_id: max(op_end[op_id] for op_id in op_ids if op_id in op_end)
        for dt_id, op_ids in dt_to_ops.items()
        if any(op_id in op_end for op_id in op_ids)
    }

    # Feed end date: ServiceCalendar.ToDate if present, otherwise max op ToDate
    feed_end_date: Optional[date] = None
    for sc in root.iter(_t("ServiceCalendar")):
        to_str = _txt(sc, "ToDate")
        if to_str:
            feed_end_date = date.fromisoformat(to_str[:10])
            break
    if feed_end_date is None and op_end:
        feed_end_date = max(op_end.values())

    return service_dates, feed_end_date, dt_weekdays, dt_op_ends


def _extend_calendar(
    service_dates: dict[str, list[str]],
    feed_end_date: date,
    dt_weekdays: dict[str, frozenset[int]],
    dt_op_ends: dict[str, date],
    extend_weeks: int,
) -> None:
    """Extend services whose last period ends within the feed's final week.

    For each qualifying DayType, the weekly pattern is repeated from the day
    after feed_end_date for extend_weeks weeks (no holiday exceptions applied).
    """
    threshold = feed_end_date - timedelta(days=6)
    extension_end = feed_end_date + timedelta(weeks=extend_weeks)
    extended = 0

    for dt_id, dates in service_dates.items():
        op_end_dt = dt_op_ends.get(dt_id)
        if op_end_dt is None or op_end_dt < threshold:
            continue
        weekdays = dt_weekdays.get(dt_id)
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


# ---------------------------------------------------------------------------
# Journey patterns
# ---------------------------------------------------------------------------

def _parse_journey_patterns(root) -> tuple[dict[str, list[dict]], dict[str, str], dict[str, str]]:
    patterns: dict[str, list[dict]] = {}
    spijp_to_ssp: dict[str, str] = {}
    pattern_to_line: dict[str, str] = {}  # pattern_id → LineRef (fallback for trips without LineRef)

    for jp in root.iter(_t("ServiceJourneyPattern")):
        jp_id = jp.get("id")
        # RouteView > LineRef is used by some producers (e.g. Trenitalia) instead of
        # putting LineRef directly on the ServiceJourney
        route_view = jp.find(_t("RouteView"))
        if route_view is not None:
            lr = route_view.find(_t("LineRef"))
            if lr is not None:
                pattern_to_line[jp_id] = lr.get("ref", "")

        pis = jp.find(_t("pointsInSequence"))
        if pis is None:
            continue
        points = []
        for spijp in sorted(pis, key=lambda e: int(e.get("order", 0))):
            ssp_ref_el = spijp.find(_t("ScheduledStopPointRef"))
            if ssp_ref_el is None:
                continue
            spijp_id = spijp.get("id")
            ssp_ref = ssp_ref_el.get("ref")
            al_el = spijp.find(_t("ForAlighting"))
            bo_el = spijp.find(_t("ForBoarding"))
            alighting = al_el is None or al_el.text.strip().lower() != "false"
            boarding = bo_el is None or bo_el.text.strip().lower() != "false"
            points.append(
                {
                    "spijp_id": spijp_id,
                    "ssp_ref": ssp_ref,
                    "for_alighting": alighting,
                    "for_boarding": boarding,
                }
            )
            spijp_to_ssp[spijp_id] = ssp_ref
        patterns[jp_id] = points

    return patterns, spijp_to_ssp, pattern_to_line


# ---------------------------------------------------------------------------
# Time helpers  (GTFS allows HH:MM:SS where HH >= 24 for post-midnight times)
# ---------------------------------------------------------------------------

def _to_seconds(t: str) -> int:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _from_seconds(secs: int) -> str:
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fix_midnight(rows: list[dict]) -> list[dict]:
    """Add 24h offset to times that cross midnight within a single trip."""
    offset = 0
    prev_dep = -1
    for row in rows:
        arr = _to_seconds(row["arrival_time"]) + offset
        dep = _to_seconds(row["departure_time"]) + offset
        # Midnight crossing between consecutive stops
        if prev_dep >= 0 and arr < prev_dep:
            offset += 86400
            arr += 86400
            dep += 86400
        # Midnight crossing between arrival and departure at the same stop
        if dep < arr:
            dep += 86400
        row["arrival_time"] = _from_seconds(arr)
        row["departure_time"] = _from_seconds(dep)
        prev_dep = dep
    return rows


# ---------------------------------------------------------------------------
# Timetable  (ServiceJourney → trips + stop_times)
# ---------------------------------------------------------------------------

def _parse_timetable(
    root, patterns: dict, pattern_to_line: dict, ssp_to_stop: dict
) -> tuple[list[dict], list[dict]]:
    trips: list[dict] = []
    stop_times: list[dict] = []

    for sj in root.iter(_t("ServiceJourney")):
        trip_id = sj.get("id")

        jp_ref_el = sj.find(_t("ServiceJourneyPatternRef"))
        jp_id = jp_ref_el.get("ref") if jp_ref_el is not None else ""
        pattern = patterns.get(jp_id, [])

        # LineRef may be on the ServiceJourney itself (ATV style) or only on the
        # pattern's RouteView (Trenitalia style) — check both
        line_ref_el = sj.find(f".//{_t('LineRef')}")
        route_id = (
            line_ref_el.get("ref")
            if line_ref_el is not None
            else pattern_to_line.get(jp_id, "")
        )

        dt_ref_el = sj.find(f".//{_t('DayTypeRef')}")
        service_id = dt_ref_el.get("ref") if dt_ref_el is not None else ""

        trips.append(
            {
                "route_id": route_id,
                "service_id": service_id,
                "trip_id": trip_id,
                "trip_headsign": _txt(sj, "Name"),
            }
        )

        # passing times indexed by StopPointInJourneyPattern ref
        # ArrivalDayOffset / DepartureDayOffset (NeTEx) encode post-midnight times explicitly
        pt_map: dict[str, dict] = {}
        pt_container = sj.find(_t("passingTimes"))
        if pt_container is not None:
            for pt in pt_container:
                spijp_ref_el = pt.find(_t("StopPointInJourneyPatternRef"))
                if spijp_ref_el is None:
                    continue
                arr_time = _txt(pt, "ArrivalTime")
                dep_time = _txt(pt, "DepartureTime")
                arr_offset = int(_txt(pt, "ArrivalDayOffset") or "0")
                dep_offset = int(_txt(pt, "DepartureDayOffset") or "0")
                if arr_time and arr_offset:
                    h, m, s = arr_time.split(":")
                    arr_time = f"{int(h) + arr_offset * 24:02d}:{m}:{s}"
                if dep_time and dep_offset:
                    h, m, s = dep_time.split(":")
                    dep_time = f"{int(h) + dep_offset * 24:02d}:{m}:{s}"
                pt_map[spijp_ref_el.get("ref")] = {
                    "arrival": arr_time,
                    "departure": dep_time,
                }

        trip_stop_times: list[dict] = []
        for seq, point in enumerate(pattern, start=1):
            pt = pt_map.get(point["spijp_id"], {})
            arrival = pt.get("arrival", "")
            departure = pt.get("departure", "")
            if not arrival:
                arrival = departure
            if not departure:
                departure = arrival

            ssp_ref = point["ssp_ref"]
            stop_id = ssp_to_stop.get(ssp_ref, ssp_ref)

            trip_stop_times.append(
                {
                    "trip_id": trip_id,
                    "arrival_time": arrival,
                    "departure_time": departure,
                    "stop_id": stop_id,
                    "stop_sequence": str(seq),
                    "pickup_type": "0" if point["for_boarding"] else "1",
                    "drop_off_type": "0" if point["for_alighting"] else "1",
                }
            )

        stop_times.extend(_fix_midnight(trip_stop_times))

    return trips, stop_times
