import zipfile
from pathlib import Path

import pytest

from converter import parser, writer

FIXTURE = Path(__file__).parent / "fixtures" / "italian_profile_sample.xml"

FLAT_TICKET = "IT:TEST:PreassignedFareProduct:BU01_BIGLIETTOURBANO"
STUDENT_PASS = "IT:TEST:PreassignedFareProduct:AM01_ABBONAMENTOMENSILESTUDENTI"
DISTANCE_TICKET = "IT:TEST:PreassignedFareProduct:EF01_CORSASEMPLICECL.01"
NETWORK_ID = "IT:TEST:NV:SAMPLE"


@pytest.fixture(scope="module")
def data() -> dict:
    return parser.parse(str(FIXTURE))


# ---------------------------------------------------------------------------
# Timetable basics
# ---------------------------------------------------------------------------

def test_agency(data):
    assert len(data["agency"]) == 1
    agency = data["agency"][0]
    assert agency["agency_name"] == "SAMPLE BUS"
    assert agency["agency_url"] == "https://www.samplebus.it"
    assert agency["agency_timezone"] == "Europe/Rome"


def test_stops(data):
    assert {s["stop_id"] for s in data["stops"]} == {
        "IT:TEST:StopPlace:1", "IT:TEST:StopPlace:2", "IT:TEST:StopPlace:3"
    }


def test_routes(data):
    assert len(data["routes"]) == 1
    route = data["routes"][0]
    assert route["route_id"] == "IT:TEST:Line:1"
    assert route["route_short_name"] == "L1"
    assert route["route_type"] == "3"


def test_trips_and_stop_times(data):
    assert {t["trip_id"] for t in data["trips"]} == {
        "IT:TEST:ServiceJourney:1", "IT:TEST:ServiceJourney:2"
    }
    for trip in data["trips"]:
        assert trip["route_id"] == "IT:TEST:Line:1"
        assert trip["service_id"] == "IT:TEST:DayType:1"

    by_trip = {}
    for st in data["stop_times"]:
        by_trip.setdefault(st["trip_id"], []).append(st)
    assert all(len(sts) == 3 for sts in by_trip.values())

    first = sorted(by_trip["IT:TEST:ServiceJourney:1"], key=lambda s: int(s["stop_sequence"]))
    assert [st["departure_time"] for st in first] == ["08:00:00", "08:11:00", "08:20:00"]
    # First stop is boarding-only, last is alighting-only
    assert (first[0]["pickup_type"], first[0]["drop_off_type"]) == ("0", "1")
    assert (first[2]["pickup_type"], first[2]["drop_off_type"]) == ("1", "0")


def test_calendar(data):
    # ValidDayBits 11111001111100 from Monday 2026-06-01 → 10 weekdays
    dates = data["service_dates"]["IT:TEST:DayType:1"]
    assert len(dates) == 10
    assert dates[0] == "2026-06-01"
    assert "2026-06-06" not in dates  # Saturday


# ---------------------------------------------------------------------------
# Fares v2
# ---------------------------------------------------------------------------

def test_fare_products(data):
    products = {(p["fare_product_id"], p["fare_media_id"]): p for p in data["fare_products"]}
    # Flat ticket sold via app + at stop → one row per medium
    assert (FLAT_TICKET, "app") in products
    assert (FLAT_TICKET, "paper") in products
    # Pass sold online only → app medium; distance ticket at stop only → paper
    assert set(k for k in products if k[0] == STUDENT_PASS) == {(STUDENT_PASS, "app")}
    assert set(k for k in products if k[0] == DISTANCE_TICKET) == {(DISTANCE_TICKET, "paper")}

    flat = products[(FLAT_TICKET, "paper")]
    assert flat["fare_product_name"] == "BU01_BIGLIETTO URBANO"
    assert flat["amount"] == "1.70"
    assert flat["currency"] == "EUR"
    assert flat["rider_category_id"] == ""

    student = products[(STUDENT_PASS, "app")]
    assert student["amount"] == "34.60"  # rounded from 34.600000000000001
    assert student["rider_category_id"] == "IT:TEST:UserProfile:student"


def test_fare_media(data):
    media = {m["fare_media_id"]: m["fare_media_type"] for m in data["fare_media"]}
    assert media == {"app": "4", "paper": "1"}


def test_rider_categories(data):
    assert data["rider_categories"] == [
        {
            "rider_category_id": "IT:TEST:UserProfile:student",
            "rider_category_name": "student",
            "is_default_fare_category": "0",
        }
    ]


def test_fare_leg_rules(data):
    # Only the flat single-ride ticket gets a leg rule: the monthly pass is not a
    # single ride and the distance-class ticket has geographical intervals.
    assert len(data["fare_leg_rules"]) == 1
    rule = data["fare_leg_rules"][0]
    assert rule["fare_product_id"] == FLAT_TICKET
    assert rule["leg_group_id"] == FLAT_TICKET
    assert rule["network_id"] == NETWORK_ID


def test_fare_transfer_rules(data):
    assert len(data["fare_transfer_rules"]) == 1
    rule = data["fare_transfer_rules"][0]
    assert rule["from_leg_group_id"] == FLAT_TICKET
    assert rule["to_leg_group_id"] == FLAT_TICKET
    assert rule["transfer_count"] == "-1"
    assert rule["duration_limit"] == "5400"  # PT90M
    assert rule["duration_limit_type"] == "1"
    assert rule["fare_transfer_type"] == "0"


def test_networks(data):
    assert data["networks"] == [{"network_id": NETWORK_ID, "network_name": "Rete TPL SAMPLE"}]
    assert data["route_networks"] == [{"network_id": NETWORK_ID, "route_id": "IT:TEST:Line:1"}]


# ---------------------------------------------------------------------------
# Writer round-trip
# ---------------------------------------------------------------------------

def test_writer_roundtrip(data, tmp_path):
    out = tmp_path / "gtfs.zip"
    writer.write(data, out)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert names == {
            "agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
            "calendar_dates.txt", "feed_info.txt", "fare_media.txt", "fare_products.txt",
            "rider_categories.txt", "fare_leg_rules.txt", "fare_transfer_rules.txt",
            "networks.txt", "route_networks.txt",
        }
        header = zf.read("fare_products.txt").decode("utf-8").splitlines()[0]
        assert header == "fare_product_id,fare_product_name,rider_category_id,fare_media_id,amount,currency"
        header = zf.read("fare_leg_rules.txt").decode("utf-8").splitlines()[0]
        assert header == "leg_group_id,network_id,from_area_id,to_area_id,fare_product_id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_duration_seconds():
    assert parser._duration_seconds("PT90M") == 5400
    assert parser._duration_seconds("PT100M") == 6000
    assert parser._duration_seconds("P7D") == 7 * 86400
    assert parser._duration_seconds("P1M") is None  # calendar-dependent
    assert parser._duration_seconds("P1Y") is None
    assert parser._duration_seconds("") is None
    assert parser._duration_seconds("garbage") is None


def test_round_amount():
    assert parser._round_amount("4.6000000000000005") == "4.60"
    assert parser._round_amount("1.7") == "1.70"
    assert parser._round_amount("2.345") == "2.35"
    assert parser._round_amount("not-a-number") is None
