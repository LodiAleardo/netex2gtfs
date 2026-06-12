"""Integration test against the real BUSITALIA ITH3 NeTEx export.

The source file is ~126 MB and excluded from version control; drop it into
``data/`` (any name matching *BUSITALIA*.xml) to enable this test.
"""
from pathlib import Path

import pytest

from converter import parser

DATA_DIR = Path(__file__).parent.parent / "data"
BUSITALIA_FILES = sorted(DATA_DIR.glob("*BUSITALIA*.xml"))

pytestmark = pytest.mark.skipif(
    not BUSITALIA_FILES, reason="BUSITALIA NeTEx file not present in data/"
)


@pytest.fixture(scope="module")
def data() -> dict:
    return parser.parse(str(BUSITALIA_FILES[0]))


def test_feed_size(data):
    assert len(data["agency"]) == 1
    assert len(data["stops"]) == 5967
    assert len(data["routes"]) == 79
    assert len(data["trips"]) == 8918
    assert len(data["service_dates"]) == 48
    assert len(data["stop_times"]) == 233470


def test_referential_integrity(data):
    route_ids = {r["route_id"] for r in data["routes"]}
    service_ids = {sid for sid, dates in data["service_dates"].items() if dates}
    stop_ids = {s["stop_id"] for s in data["stops"]}
    trip_ids = {t["trip_id"] for t in data["trips"]}

    assert all(t["route_id"] in route_ids for t in data["trips"])
    assert all(t["service_id"] in service_ids for t in data["trips"])
    assert all(st["stop_id"] in stop_ids for st in data["stop_times"])
    assert all(st["trip_id"] in trip_ids for st in data["stop_times"])

    per_trip: dict[str, int] = {}
    for st in data["stop_times"]:
        per_trip[st["trip_id"]] = per_trip.get(st["trip_id"], 0) + 1
    assert set(per_trip) == trip_ids
    assert min(per_trip.values()) >= 2


def test_fares_v2(data):
    product_rows = data["fare_products"]
    assert len(product_rows) == 111  # 60 products, most sold both on paper and app
    assert len({p["fare_product_id"] for p in product_rows}) == 60

    media_ids = {m["fare_media_id"] for m in data["fare_media"]}
    category_ids = {c["rider_category_id"] for c in data["rider_categories"]}
    for p in product_rows:
        assert p["currency"] == "EUR"
        # amounts are positive, normalised to 2 decimals
        assert float(p["amount"]) > 0
        assert len(p["amount"].split(".")[1]) == 2
        assert p["fare_media_id"] in media_ids | {""}
        assert p["rider_category_id"] in category_ids | {""}

    # Leg rules: only the flat urban single tickets (no carnets, no distance classes)
    product_ids = {p["fare_product_id"] for p in product_rows}
    leg_rules = data["fare_leg_rules"]
    assert len(leg_rules) == 3
    network_ids = {n["network_id"] for n in data["networks"]}
    for rule in leg_rules:
        assert rule["fare_product_id"] in product_ids
        assert rule["network_id"] in network_ids
        assert "CARNET" not in rule["fare_product_id"].upper()

    leg_groups = {r["leg_group_id"] for r in leg_rules}
    transfer_rules = data["fare_transfer_rules"]
    assert len(transfer_rules) == 3
    for rule in transfer_rules:
        assert rule["from_leg_group_id"] in leg_groups
        assert rule["to_leg_group_id"] in leg_groups
        assert rule["duration_limit"] in {"5400", "6000"}  # 90 and 100 minute tickets

    # Every route is assigned to the single network exactly once
    assert len(data["networks"]) == 1
    route_ids = {r["route_id"] for r in data["routes"]}
    assigned = [rn["route_id"] for rn in data["route_networks"]]
    assert sorted(assigned) == sorted(route_ids)
