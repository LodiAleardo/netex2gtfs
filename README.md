# netex2gtfs

A Python tool to convert [NeTEx](https://netex-cen.eu/) (Network Timetable Exchange) XML files into [GTFS](https://gtfs.org/) (General Transit Feed Specification) static feeds.

## Overview

NeTEx is a CEN European standard for exchanging public transport schedules and related data. 
GTFS is the de facto standard consumed by trip planners (Google Maps, OpenTripPlanner, Transitland, etc.). 
This tool bridges the two formats, with a **focus on Italian regional feeds** published under the national open-data program.

## Features

- Converts NeTEx XML to a valid GTFS static zip
- Produces `agency.txt`, `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt`, `calendar_dates.txt`, `feed_info.txt`
- Full [GTFS-Fares v2](https://gtfs.org/community/extensions/fares-v2/) output from EPIP FareFrames
  (Italian profile): `fare_products.txt`, `fare_media.txt`, `rider_categories.txt`,
  `fare_leg_rules.txt`, `fare_transfer_rules.txt`, `networks.txt`, `route_networks.txt`
- Outputs `areas.txt` and `stop_areas.txt` (GTFS-Fares v2) when tariff zone data is present
- Handles timezone-aware NeTEx times, post-midnight times via day offsets, and ValidDayBits calendars
- Maps NeTEx transport modes to GTFS route types including funicular, cableway, rail, ferry, and water
- Cleans and normalises agency phone numbers and URLs from source data
- Optional calendar extension: repeats the last week's pattern beyond the feed end date
- Batch validation script using the [MobilityData GTFS Validator](https://github.com/MobilityData/gtfs-validator)

## Requirements

- Python 3.10+
- Java runtime (provided automatically via `jdk4py`)
- See `requirements.txt`

## Installation

```bash
git clone https://github.com/LodiAleardo/netex2gtfs.git
cd netex2gtfs
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

### Convert a single file

```bash
python main.py --input data/your_netex_file.xml --output output/gtfs.zip
```

| Flag | Description | Default |
|------|-------------|---------|
| `--input` | Path to NeTEx XML file | required |
| `--output` | Path for the output GTFS zip | `output/gtfs.zip` |
| `--extend-calendar-weeks` | Extend the feed N weeks beyond its end date by repeating weekday patterns | `0` |
| `--verbose` | Enable verbose logging | off |

### Validate all files in `data/`

```bash
python validate.py
```

Converts every `.xml` in `data/`, runs the GTFS validator against each output, and reports any ERROR-severity notices. Requires `gtfs-validator.jar` at `.cache/gtfs-validator.jar`.

### Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

Unit tests run against a small NeTEx Italian-profile fixture in `tests/fixtures/`.
An additional integration test runs automatically when a BUSITALIA NeTEx export
(any file matching `*BUSITALIA*.xml`) is present in `data/`, and is skipped otherwise.

## Input data

Place NeTEx XML files in the `data/` directory.
They are excluded from version control via `.gitignore` due to file size. T
he converter has been tested against the Italian national NeTEx open-data exports available at [dati.gov.it](https://www.dati.gov.it/).

## Output

The converter produces a standard GTFS static zip.
Files included depend on source data:

| File | Always present | Condition |
|------|---------------|-----------|
| `agency.txt` | yes | |
| `stops.txt` | yes | |
| `routes.txt` | yes | |
| `trips.txt` | yes | |
| `stop_times.txt` | yes | |
| `calendar_dates.txt` | yes | |
| `feed_info.txt` | yes | |
| `areas.txt` | no | TariffZone elements present |
| `stop_areas.txt` | no | TariffZone assignments present |
| `fare_products.txt` | no | FareFrame with priced SalesOfferPackages present |
| `fare_media.txt` | no | DistributionChannels present (mapped to paper / mobile app) |
| `rider_categories.txt` | no | UserProfiles referenced by fare products |
| `fare_leg_rules.txt` | no | Flat single-ride products present (see note below) |
| `fare_transfer_rules.txt` | no | Single-ride products with a time validity (e.g. 90 min) |
| `networks.txt` / `route_networks.txt` | no | NeTEx Network present and fare leg rules produced |

### Fares v2 notes

Fares are read from the EPIP `FareFrame` following the NeTEx
[Italian profile](https://github.com/5Tsrl/netex-italian-profile) reference chain
(`SalesOfferPackage` → `FareTable` → `FareStructureElementPrice` → `FareStructureElement`).
Known limitations, driven by what Italian feeds actually contain:

- Distance-class tariffs (`GeographicalInterval` km bands) and multi-ride carnets are
  exported as priced `fare_products.txt` entries but get no `fare_leg_rules.txt` rows:
  GTFS has no distance-based pricing and a carnet price covers several rides.
- Single-ride tickets with a time validity (e.g. valid 90 minutes) produce a
  `fare_transfer_rules.txt` row allowing unlimited free transfers within that window.
- `timeframes.txt` is not produced (no time-of-day fare variation in the source data).


## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).  
Copyright (C) 2026 Aleardo Lodi
