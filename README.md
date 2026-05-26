# netex2gtfs

A Python tool to convert [NeTEx](https://netex-cen.eu/) (Network Timetable Exchange) XML files into [GTFS](https://gtfs.org/) (General Transit Feed Specification) static feeds.

## Overview

NeTEx is a CEN European standard for exchanging public transport schedules and related data. 
GTFS is the de facto standard consumed by trip planners (Google Maps, OpenTripPlanner, Transitland, etc.). 
This tool bridges the two formats, with a **focus on Italian regional feeds** published under the national open-data program.

## Features

- Converts NeTEx XML to a valid GTFS static zip
- Produces `agency.txt`, `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt`, `calendar_dates.txt`, `feed_info.txt`
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


## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).  
Copyright (C) 2026 Aleardo Lodi
