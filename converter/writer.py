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
_FARE_MEDIA_FIELDS = ["fare_media_id", "fare_media_name", "fare_media_type"]
_FARE_PRODUCTS_FIELDS = [
    "fare_product_id", "fare_product_name", "rider_category_id",
    "fare_media_id", "amount", "currency"]
_RIDER_CATEGORIES_FIELDS = ["rider_category_id", "rider_category_name", "is_default_fare_category"]
_FARE_LEG_RULES_FIELDS = ["leg_group_id", "network_id", "from_area_id", "to_area_id", "fare_product_id"]
_FARE_TRANSFER_RULES_FIELDS = [
    "from_leg_group_id", "to_leg_group_id", "transfer_count",
    "duration_limit", "duration_limit_type", "fare_transfer_type"]
_NETWORKS_FIELDS = ["network_id", "network_name"]
_ROUTE_NETWORKS_FIELDS = ["network_id", "route_id"]

# Optional Fares v2 files, written only when the parser produced rows for them.
_OPTIONAL_FILES = {
    "areas.txt": ("areas", _AREAS_FIELDS),
    "stop_areas.txt": ("stop_areas", _STOP_AREAS_FIELDS),
    "fare_media.txt": ("fare_media", _FARE_MEDIA_FIELDS),
    "fare_products.txt": ("fare_products", _FARE_PRODUCTS_FIELDS),
    "rider_categories.txt": ("rider_categories", _RIDER_CATEGORIES_FIELDS),
    "fare_leg_rules.txt": ("fare_leg_rules", _FARE_LEG_RULES_FIELDS),
    "fare_transfer_rules.txt": ("fare_transfer_rules", _FARE_TRANSFER_RULES_FIELDS),
    "networks.txt": ("networks", _NETWORKS_FIELDS),
    "route_networks.txt": ("route_networks", _ROUTE_NETWORKS_FIELDS),
}


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

    for filename, (key, fields) in _OPTIONAL_FILES.items():
        if data.get(key):
            files[filename] = (fields, data[key])

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, (fields, rows) in files.items():
            zf.writestr(filename, _csv_bytes(fields, rows))
            log.info("  wrote %s (%d rows)", filename, len(rows))

    log.info("GTFS feed written to %s", output_path)
