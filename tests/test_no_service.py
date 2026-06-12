"""Behaviour on NeTEx files without scheduled service (e.g. vehicle-sharing exports).

Italian NAP alternative-modes feeds (such as e-scooter operators) contain only a
SiteFrame and a FareFrame: no lines, journeys or calendars. They cannot become a
GTFS static feed, so the CLI must refuse them with a clear message instead of
writing a stops-only zip.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from converter import parser

REPO_ROOT = Path(__file__).parent.parent

NO_SERVICE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<PublicationDelivery xmlns="http://www.netex.org.uk/netex">
    <PublicationTimestamp>2026-06-11T04:04:48.000+02:00</PublicationTimestamp>
    <ParticipantRef>RAPLazio</ParticipantRef>
    <dataObjects>
        <CompositeFrame id="epd:IT:TEST:CompositeFrame-EU_PI_LINE_OFFER:sharing" version="1">
            <TypeOfFrameRef versionRef="1" ref="epip:EU_PI_LINE_OFFER"/>
            <frames>
                <ResourceFrame id="epd:IT:TEST:ResourceFrame:sharing" version="1">
                    <organisations>
                        <Operator id="IT:TEST:Operator:SHARING" version="1">
                            <Name>Sharing Co</Name>
                        </Operator>
                    </organisations>
                </ResourceFrame>
                <SiteFrame id="epd:IT:TEST:SiteFrame:sharing" version="1">
                    <stopPlaces>
                        <StopPlace id="IT:TEST:StopPlace:HUB1" version="1">
                            <Name>Mobility hub 1</Name>
                            <Centroid>
                                <Location>
                                    <Longitude>12.49000</Longitude>
                                    <Latitude>41.89000</Latitude>
                                </Location>
                            </Centroid>
                        </StopPlace>
                    </stopPlaces>
                </SiteFrame>
                <FareFrame id="epd:IT:TEST:FareFrame:sharing" version="1">
                    <FrameDefaults>
                        <DefaultCurrency>EUR</DefaultCurrency>
                    </FrameDefaults>
                    <fareProducts>
                        <PreassignedFareProduct id="IT:TEST:PreassignedFareProduct:UNLOCK" version="1">
                            <Name>Sblocco mezzo</Name>
                        </PreassignedFareProduct>
                    </fareProducts>
                </FareFrame>
            </frames>
        </CompositeFrame>
    </dataObjects>
</PublicationDelivery>
"""


@pytest.fixture()
def no_service_file(tmp_path) -> Path:
    path = tmp_path / "sharing.xml"
    path.write_text(NO_SERVICE_XML, encoding="utf-8")
    return path


def test_parse_yields_no_trips_and_no_fares(no_service_file):
    data = parser.parse(str(no_service_file))
    assert data["trips"] == []
    assert data["stop_times"] == []
    assert data["routes"] == []
    # Unpriced fare products cannot become fare_products.txt rows (amount is required)
    assert data["fare_products"] == []
    assert data["fare_leg_rules"] == []


def test_cli_refuses_feed_without_service(no_service_file, tmp_path):
    out = tmp_path / "gtfs.zip"
    result = subprocess.run(
        [sys.executable, "main.py", "--input", str(no_service_file), "--output", str(out)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "No scheduled service" in result.stderr
    assert not out.exists()
