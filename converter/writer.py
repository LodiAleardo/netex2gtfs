import csv
import io
import logging
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

_AGENCY_FIELDS = ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang", "agency_phone"]
_STOPS_FIELDS = ["stop_id", "stop_name", "stop_lat", "stop_lon"]
_ROUTES_FIELDS = ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type", "route_desc"]
_TRIPS_FIELDS = ["route_id", "service_id", "trip_id", "trip_headsign"]
_STOP_TIMES_FIELDS = [
    "trip_id", "arrival_time", "departure_time", "stop_id",
    "stop_sequence", "pickup_type", "drop_off_type"]
_CALENDAR_DATES_FIELDS = ["service_id", "date", "exception_type"]
_FEED_INFO_FIELDS = [
    "feed_publisher_name", "feed_publisher_url", "feed_lang",
    "feed_start_date", "feed_end_date", "feed_version",
    "feed_contact_email", "feed_contact_url"]
_AREAS_FIELDS = ["area_id", "area_name"]
_STOP_AREAS_FIELDS = ["stop_id", "area_id"]


def _csv_bytes(fields: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _calendar_dates_rows(service_dates: dict[str, list[str]]) -> list[dict]:
    rows = []
    for service_id, dates in service_dates.items():
        for d in dates:
            rows.append(
                {
                    "service_id": service_id,
                    "date": d.replace("-", ""),  # GTFS format: YYYYMMDD
                    "exception_type": "1",
                }
            )
    return rows


def write(data: dict, output_path: Path) -> None:
    """Serialize a parsed GTFS data dict to a zipped GTFS feed at output_path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    files = {
        "agency.txt": (_AGENCY_FIELDS, data["agency"]),
        "stops.txt": (_STOPS_FIELDS, data["stops"]),
        "routes.txt": (_ROUTES_FIELDS, data["routes"]),
        "trips.txt": (_TRIPS_FIELDS, data["trips"]),
        "stop_times.txt": (_STOP_TIMES_FIELDS, data["stop_times"]),
        "calendar_dates.txt": (_CALENDAR_DATES_FIELDS, _calendar_dates_rows(data["service_dates"])),
        "feed_info.txt": (_FEED_INFO_FIELDS, data["feed_info"]),
    }

    if data.get("areas"):
        files["areas.txt"] = (_AREAS_FIELDS, data["areas"])
    if data.get("stop_areas"):
        files["stop_areas.txt"] = (_STOP_AREAS_FIELDS, data["stop_areas"])

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, (fields, rows) in files.items():
            zf.writestr(filename, _csv_bytes(fields, rows))
            log.info("  wrote %s (%d rows)", filename, len(rows))

    log.info("GTFS feed written to %s", output_path)
