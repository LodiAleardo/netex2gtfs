import io
import logging
import re
import xml.etree.ElementTree as ElementTree
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from converter.extender import extend_calendar

NS = "http://www.netex.org.uk/netex"

DAY_OF_THE_WEEK_TO_CARDINAL = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}

TRANSPORT_TYPE = {
    "tram": 0,
    "metro": 1,
    "rail": 2,
    "bus": 3,
    "coach": 3,
    "ferry": 4,
    "water": 4,
    "cableway": 6,
    "lift": 6,
    "funicular": 7,
}

log = logging.getLogger(__name__)


def _t(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _txt(el, tag: str, default: str = "") -> str:
    child = el.find(_t(tag))
    if child is None or not child.text:
        return default
    return child.text.strip().replace("�", "")


def load_xml(xml_path: str) -> ElementTree.Element:
    """Parse XML without encoding fallback for files that declare UTF-8 but contain Latin-1 bytes."""
    # ToDo: I could throw ElementTree.ParseError but for the moment ignoring
    with open(xml_path, "rb") as f:
        return ElementTree.parse(io.BytesIO(f.read())).getroot()

def parse(xml_path: str, extend_calendar_weeks: int = 0) -> dict:
    log.info("Parsing %s", xml_path)
    root = load_xml(xml_path)

    agencies = _parse_agencies(root)
    stops, ssp_to_stop = _parse_stops(root)
    routes = _parse_routes(root)
    service_dates, feed_end_date, dt_weekdays, dt_op_ends = _parse_calendar(root)
    if extend_calendar_weeks > 0 and feed_end_date is not None:
        extend_calendar(service_dates, feed_end_date, dt_weekdays, extend_calendar_weeks)
    patterns, spijp_to_ssp, pattern_to_line = _parse_journey_patterns(root)
    trips, stop_times = _parse_timetable(root, patterns, pattern_to_line, ssp_to_stop)

    # Drop trips whose service has no active dates and stop_times referencing unknown stops.
    valid_services = {sid for sid, dates in service_dates.items() if dates}
    trips = [t for t in trips if t["service_id"] in valid_services]

    # Deduplicate trips by trip_id (NeTEx may repeat the same id with different versions).
    trips_by_id: dict[str, dict] = {}
    for t in trips:
        trips_by_id[t["trip_id"]] = t
    trips = list(trips_by_id.values())

    # Remap trip route_ids that reference a parent line not present in routes.
    # Some producers (e.g. Tuscany) use FlexibleLineView to reference a logical
    # parent ID (e.g. "Line:foo") while only variant routes exist (e.g. "Line:foo_3@V1").
    valid_route_ids = {r["route_id"] for r in routes}
    missing_ids = {t["route_id"] for t in trips if t["route_id"] not in valid_route_ids}
    if missing_ids:
        prefix_map: dict[str, str] = {}
        for mid in missing_ids:
            for r in routes:
                if r["route_id"].startswith(mid):
                    prefix_map[mid] = r["route_id"]
                    break
        if prefix_map:
            trips = [
                {**t, "route_id": prefix_map[t["route_id"]]}
                if t["route_id"] in prefix_map else t
                for t in trips
            ]

    valid_trip_ids = {t["trip_id"] for t in trips}
    valid_stop_ids = {s["stop_id"] for s in stops}
    stop_times = [
        st for st in stop_times
        if st["trip_id"] in valid_trip_ids and st["stop_id"] in valid_stop_ids
    ]

    # Deduplicate stop_times by (trip_id, stop_sequence) — last version wins,
    # consistent with trip/route deduplication above.
    st_by_key: dict[tuple, dict] = {}
    for st in stop_times:
        st_by_key[(st["trip_id"], st["stop_sequence"])] = st
    stop_times = list(st_by_key.values())

    feed_info = _parse_feed_info(root, agencies, service_dates)
    fares = _parse_fares(root, ssp_to_stop)
    fares["stop_areas"] = [sa for sa in fares["stop_areas"] if sa["stop_id"] in valid_stop_ids]
    area_ids = {a["area_id"] for a in fares["areas"]}
    fares_v2 = _parse_fares_v2(root, routes, area_ids)

    log.info(
        "Parsed: %d agencies, %d stops, %d routes, %d services, %d trips, %d stop_times, %d areas, %d stop_areas",
        len(agencies), len(stops), len(routes), len(service_dates),
        len(trips), len(stop_times), len(fares["areas"]), len(fares["stop_areas"]),
    )
    if fares_v2["fare_products"]:
        log.info(
            "Parsed fares v2: %d fare_products, %d fare_media, %d rider_categories, "
            "%d fare_leg_rules, %d fare_transfer_rules, %d networks",
            len(fares_v2["fare_products"]), len(fares_v2["fare_media"]),
            len(fares_v2["rider_categories"]), len(fares_v2["fare_leg_rules"]),
            len(fares_v2["fare_transfer_rules"]), len(fares_v2["networks"]),
        )
    return {
        "agency": agencies,
        "stops": stops,
        "routes": routes,
        "service_dates": service_dates,
        "trips": trips,
        "stop_times": stop_times,
        "feed_info": feed_info,
        "areas": fares["areas"],
        "stop_areas": fares["stop_areas"],
        **fares_v2,
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

_PHONE_SENTINELS = {"none", "n/a", "na", "nd", "-"}


def _clean_phone(phone: str) -> str:
    if not phone:
        return phone
    if phone.strip().lower() in _PHONE_SENTINELS:
        return ""
    if not re.search(r"\d", phone):
        return ""
    # Strip trailing free-text annotation after " - " (e.g. "- WhatsApp")
    phone = re.sub(r"\s*-\s*[A-Za-z].*$", "", phone).strip()
    # Drop a second number appended with "-" only when the prefix is already a
    # complete number (≥8 digits). e.g. "+39 0873 378788-391168" → "+39 0873 378788"
    # but leave "0331-707700" (Italian area-code + number) untouched.
    m = re.search(r"-\d{6,}$", phone)
    if m:
        prefix = phone[:m.start()]
        if len(re.sub(r"\D", "", prefix)) >= 8:
            phone = prefix.strip()
    # Convert (CC) country-code prefix to +CC (e.g. "(39) 351…" → "+39 351…")
    phone = re.sub(r"^\((\d+)\)\s*", r"+\1 ", phone)
    return phone


def _normalize_url(url: str) -> str:
    if not url:
        return url
    url = re.sub(r"^(https?):\\\\", r"\1://", url)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # Reject URLs whose host part has no dot (e.g. "https://n/a")
    try:
        from urllib.parse import urlparse
        if "." not in (urlparse(url).netloc or ""):
            return ""
    except Exception:
        return ""
    return url


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
                "agency_url": _normalize_url(url),
                "agency_timezone": "Europe/Rome",
                "agency_lang": "it",
                "agency_phone": _clean_phone(phone),
            }
        )
    # Fill missing URLs: prefer the first valid URL found in this feed so that
    # multi-agency feeds share a contextually relevant URL. When no agency in the
    # feed has a URL at all, fall back to the Italian transport ministry portal.
    feed_url = next(
        (a["agency_url"] for a in agencies if a["agency_url"]),
        "https://www.mit.gov.it/",
    )
    for a in agencies:
        if not a["agency_url"]:
            a["agency_url"] = feed_url
    return agencies


# ---------------------------------------------------------------------------
# Stops
# ---------------------------------------------------------------------------

def _parse_stops(root) -> tuple[list[dict], dict[str, str]]:
    stops = []
    for sp in root.iter(_t("StopPlace")):
        centroid = sp.find(_t("Centroid"))
        if centroid is None:
            # IT-ITH3-BIV_GOMMA_L1.xml places coordinates on the Quay, not on the StopPlace
            quays_el = sp.find(_t("quays"))
            if quays_el is not None:
                for quay in quays_el:
                    c = quay.find(_t("Centroid"))
                    if c is not None:
                        centroid = c
                        break
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

    # IT-ITC4-APAM: no PassengerStopAssignment — ScheduledStopPoint carries coordinates
    # directly and is referenced by stop_times. Add unmapped SSPs as stops.
    for ssp in root.iter(_t("ScheduledStopPoint")):
        ssp_id = ssp.get("id")
        if ssp_id in ssp_to_stop:
            continue
        loc = ssp.find(_t("Location"))
        if loc is None:
            continue
        lat_el = loc.find(_t("Latitude"))
        lon_el = loc.find(_t("Longitude"))
        if lat_el is None or lon_el is None:
            continue
        stops.append(
            {
                "stop_id": ssp_id,
                "stop_name": _txt(ssp, "Name"),
                "stop_lat": lat_el.text.strip(),
                "stop_lon": lon_el.text.strip(),
            }
        )

    return stops, ssp_to_stop


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _parse_routes(root) -> list[dict]:
    # NeTEx allows multiple versions of the same element — keep the last (highest version).
    routes_by_id: dict[str, dict] = {}
    for line in root.iter(_t("Line")):
        op_ref = line.find(_t("OperatorRef"))
        mode = _txt(line, "TransportMode", "bus").strip().lower()
        routes_by_id[line.get("id")] = {
            "route_id": line.get("id"),
            "agency_id": op_ref.get("ref") if op_ref is not None else "",
            "route_short_name": _txt(line, "ShortName") or _txt(line, "PublicCode"),
            "route_long_name": _txt(line, "Name"),
            "route_type": str(TRANSPORT_TYPE.get(mode, 3)),
            "route_desc": _txt(line, "Description"),
        }
    return list(routes_by_id.values())


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
        days = frozenset(DAY_OF_THE_WEEK_TO_CARDINAL[d] for d in dow_el.text.split() if d in DAY_OF_THE_WEEK_TO_CARDINAL)
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

        if not route_id:
            continue

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
        # Times may include a timezone offset (e.g. "06:21:00+01:00") — strip to HH:MM:SS.
        pt_map: dict[str, dict] = {}
        pt_container = sj.find(_t("passingTimes"))
        if pt_container is not None:
            for pt in pt_container:
                spijp_ref_el = pt.find(_t("StopPointInJourneyPatternRef"))
                if spijp_ref_el is None:
                    continue
                arr_time = _txt(pt, "ArrivalTime")[:8]
                dep_time = _txt(pt, "DepartureTime")[:8]
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
            if not arrival and not departure:
                continue

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


# ---------------------------------------------------------------------------
# Fares  (TariffZone → areas, SSP zone refs → stop_areas)
# ---------------------------------------------------------------------------

def _parse_fares(root, ssp_to_stop: dict[str, str]) -> dict:
    areas = []
    seen_areas: set[str] = set()
    for tz in root.iter(_t("TariffZone")):
        area_id = tz.get("id")
        if not area_id or area_id in seen_areas:
            continue
        seen_areas.add(area_id)
        name = _txt(tz, "Description") or _txt(tz, "Name") or area_id
        areas.append({"area_id": area_id, "area_name": name})

    stop_areas = []
    seen_pairs: set[tuple[str, str]] = set()
    for ssp in root.iter(_t("ScheduledStopPoint")):
        ssp_id = ssp.get("id")
        tz_el = ssp.find(_t("tariffZones"))
        if tz_el is None:
            continue
        stop_id = ssp_to_stop.get(ssp_id, ssp_id)
        for tzref in tz_el:
            area_id = tzref.get("ref")
            if not area_id:
                continue
            pair = (stop_id, area_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            stop_areas.append({"stop_id": stop_id, "area_id": area_id})

    return {"areas": areas, "stop_areas": stop_areas}


# ---------------------------------------------------------------------------
# Fares v2  (EPIP FareFrame → fare_products, fare_media, rider_categories,
#            fare_leg_rules, fare_transfer_rules, networks, route_networks)
#
# Reference chain in the Italian profile:
#   SalesOfferPackage > SalesOfferPackageElement holds FareProductRef + FareTableRef;
#   FareTable > FareStructureElementPrice carries the Amount and points back to the
#   Tariff's FareStructureElement, whose GenericParameterAssignment limitations carry
#   UserProfileRef (rider category) and UsageValidityPeriodRef (single ride vs pass).
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"^P(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

_FARE_PRODUCT_TAGS = ("PreassignedFareProduct", "AmountOfPriceUnitProduct")

# fare_media_type: 1 = physical paper ticket, 4 = mobile app
_MEDIA_DEFS = {
    "paper": {"fare_media_id": "paper", "fare_media_name": "Paper ticket", "fare_media_type": "1"},
    "app": {"fare_media_id": "app", "fare_media_name": "Mobile app", "fare_media_type": "4"},
}
_APP_CHANNEL_KEYWORDS = ("app", "online", "telephone", "mobile")


def _duration_seconds(duration: str) -> Optional[int]:
    """ISO-8601 duration → seconds; None for calendar-dependent (years/months) or unparsable values."""
    if not duration:
        return None
    m = _DURATION_RE.match(duration.strip())
    if m is None:
        return None
    parts = {k: v for k, v in m.groupdict().items() if v is not None}
    if not parts:
        return None
    if int(parts.get("years", 0)) or int(parts.get("months", 0)):
        return None
    return (
        int(parts.get("days", 0)) * 86400
        + int(parts.get("hours", 0)) * 3600
        + int(parts.get("minutes", 0)) * 60
        + int(float(parts.get("seconds", 0)))
    )


def _round_amount(amount: str) -> Optional[str]:
    """Normalise a NeTEx price (e.g. "4.6000000000000005") to 2 decimals."""
    try:
        return str(Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def _ref(el, tag: str) -> str:
    child = el.find(_t(tag))
    return child.get("ref", "") if child is not None else ""


def _parse_fares_v2(root, routes: list[dict], area_ids: set[str]) -> dict:
    empty = {
        "fare_media": [], "fare_products": [], "rider_categories": [],
        "fare_leg_rules": [], "fare_transfer_rules": [],
        "networks": [], "route_networks": [],
    }

    # Currency from FareFrame FrameDefaults
    currency = "EUR"
    for ff in root.iter(_t("FareFrame")):
        defaults = ff.find(_t("FrameDefaults"))
        if defaults is not None and _txt(defaults, "DefaultCurrency"):
            currency = _txt(defaults, "DefaultCurrency")
        break

    # UsageValidityPeriod id → (type, seconds)
    validity_periods: dict[str, dict] = {}
    for uvp in root.iter(_t("UsageValidityPeriod")):
        validity_periods[uvp.get("id")] = {
            "type": _txt(uvp, "ValidityPeriodType"),
            "seconds": _duration_seconds(_txt(uvp, "StandardDuration")),
        }

    # UserProfile → rider_categories
    rider_categories = []
    for up in root.iter(_t("UserProfile")):
        up_id = up.get("id")
        name = _txt(up, "Name") or _txt(up, "UserType") or up_id.split(":")[-1]
        rider_categories.append(
            {
                "rider_category_id": up_id,
                "rider_category_name": name,
                "is_default_fare_category": "0",
            }
        )

    # FareStructureElement id → rider category / validity period / distance-class flag
    fse_info: dict[str, dict] = {}
    for fse in root.iter(_t("FareStructureElement")):
        info = {"user_profile": "", "validity_period": "", "has_geo": fse.find(_t("geographicalIntervals")) is not None}
        for lim in fse.iter(_t("limitations")):
            info["user_profile"] = info["user_profile"] or _ref(lim, "UserProfileRef")
            info["validity_period"] = info["validity_period"] or _ref(lim, "UsageValidityPeriodRef")
        # Zone-scoped tariffs (other Italian feeds): TariffZoneRef/FareZoneRef in validityParameters
        zones = []
        for vp in fse.iter(_t("validityParameters")):
            for tag in ("TariffZoneRef", "FareZoneRef"):
                zones.extend(z.get("ref") for z in vp.iter(_t(tag)) if z.get("ref"))
        info["zones"] = [z for z in zones if z in area_ids]
        fse_info[fse.get("id")] = info

    # FareTable id → list of (FareStructureElementRef, Amount)
    fare_tables: dict[str, list[tuple[str, str]]] = {}
    for ft in root.iter(_t("FareTable")):
        prices = []
        for price in ft.iter(_t("FareStructureElementPrice")):
            amount = _txt(price, "Amount")
            if amount:
                prices.append((_ref(price, "FareStructureElementRef"), amount))
        fare_tables[ft.get("id")] = prices

    # Fare product id → name; multi-ride bundles are excluded from leg rules below
    # because their price covers several rides, not one leg. AmountOfPriceUnitProduct
    # is the structural marker, but Italian producers also model carnets as
    # PreassignedFareProduct with only the name ("CARNET ...") telling them apart.
    product_names: dict[str, str] = {}
    bundle_products: set[str] = set()
    for tag in _FARE_PRODUCT_TAGS:
        for fp in root.iter(_t(tag)):
            fp_id = fp.get("id")
            product_names[fp_id] = _txt(fp, "Name")
            if tag == "AmountOfPriceUnitProduct" or "carnet" in product_names[fp_id].lower():
                bundle_products.add(fp_id)

    # DistributionChannel id → media key ("app" / "paper")
    channel_media: dict[str, str] = {}
    for dc in root.iter(_t("DistributionChannel")):
        text = (dc.get("id", "") + _txt(dc, "Name")).lower()
        channel_media[dc.get("id")] = (
            "app" if any(k in text for k in _APP_CHANNEL_KEYWORDS) else "paper"
        )

    # SalesOfferPackage: tie product ↔ price ↔ media, derive leg/transfer rules
    fare_products: list[dict] = []
    fare_leg_rules: list[dict] = []
    fare_transfer_rules: list[dict] = []
    used_media: set[str] = set()
    seen_products: set[tuple] = set()
    seen_leg_groups: set[str] = set()

    for sop in root.iter(_t("SalesOfferPackage")):
        media_ids = sorted(
            {
                channel_media[ref]
                for da in sop.iter(_t("DistributionAssignment"))
                if (ref := _ref(da, "DistributionChannelRef")) in channel_media
            }
        ) or [""]

        for el in sop.iter(_t("SalesOfferPackageElement")):
            product_id = _ref(el, "FareProductRef")
            if not product_id:
                continue

            # First resolvable price among the element's fare tables
            fse_ref, amount = "", None
            tables_el = el.find(_t("fareTables"))
            table_refs = (
                [t.get("ref") for t in tables_el.iter(_t("FareTableRef"))]
                if tables_el is not None else []
            )
            for table_ref in table_refs:
                for ref, raw_amount in fare_tables.get(table_ref, []):
                    rounded = _round_amount(raw_amount)
                    if rounded is not None:
                        fse_ref, amount = ref, rounded
                        break
                if amount is not None:
                    break
            if amount is None:
                log.warning("Fare product %s has no resolvable price, skipping", product_id)
                continue

            info = fse_info.get(fse_ref, {})
            rider_category = info.get("user_profile", "")
            for media_id in media_ids:
                key = (product_id, rider_category, media_id)
                if key in seen_products:
                    continue
                seen_products.add(key)
                if media_id:
                    used_media.add(media_id)
                fare_products.append(
                    {
                        "fare_product_id": product_id,
                        "fare_product_name": product_names.get(product_id, ""),
                        "rider_category_id": rider_category,
                        "fare_media_id": media_id,
                        "amount": amount,
                        "currency": currency,
                    }
                )

            # Leg rules only for flat single-ride tickets: distance-class fares
            # (geographical intervals) cannot be priced without OD areas in GTFS.
            validity = validity_periods.get(info.get("validity_period", ""), {})
            if validity.get("type") != "singleRide" or info.get("has_geo") or product_id in bundle_products:
                continue
            if product_id in seen_leg_groups:
                continue
            seen_leg_groups.add(product_id)

            zones = info.get("zones") or [""]
            for zone in zones:
                fare_leg_rules.append(
                    {
                        "leg_group_id": product_id,
                        "network_id": "",  # filled below once the Network is known
                        "from_area_id": zone,
                        "to_area_id": zone,
                        "fare_product_id": product_id,
                    }
                )
            if validity.get("seconds"):
                fare_transfer_rules.append(
                    {
                        "from_leg_group_id": product_id,
                        "to_leg_group_id": product_id,
                        "transfer_count": "-1",
                        "duration_limit": str(validity["seconds"]),
                        "duration_limit_type": "1",  # departure to departure
                        "fare_transfer_type": "0",  # from-leg cost + free transfer (A + AB)
                    }
                )

    if not fare_products:
        return empty

    used_categories = {fp["rider_category_id"] for fp in fare_products if fp["rider_category_id"]}
    rider_categories = [rc for rc in rider_categories if rc["rider_category_id"] in used_categories]

    # Scope leg rules to the feed's Network when one exists; networks.txt and
    # route_networks.txt are only needed when leg rules reference a network.
    networks: list[dict] = []
    route_networks: list[dict] = []
    network_el = next(root.iter(_t("Network")), None)
    if network_el is not None and fare_leg_rules:
        network_id = network_el.get("id")
        networks.append({"network_id": network_id, "network_name": _txt(network_el, "Name")})
        route_networks = [
            {"network_id": network_id, "route_id": r["route_id"]} for r in routes
        ]
        for rule in fare_leg_rules:
            rule["network_id"] = network_id

    return {
        "fare_media": [_MEDIA_DEFS[m] for m in sorted(used_media)],
        "fare_products": fare_products,
        "rider_categories": rider_categories,
        "fare_leg_rules": fare_leg_rules,
        "fare_transfer_rules": fare_transfer_rules,
        "networks": networks,
        "route_networks": route_networks,
    }
