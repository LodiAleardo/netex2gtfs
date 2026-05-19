# netex2gtfs

A Python tool to convert [NeTEx](https://netex-cen.eu/) (Network Timetable Exchange) XML files into [GTFS](https://gtfs.org/) (General Transit Feed Specification) format.

## Overview

NeTEx is a CEN European standard for exchanging public transport schedules and related data. GTFS is the de facto standard used by trip planners (Google Maps, OpenTripPlanner, etc.). This tool bridges the two formats.

## Features

- Parse NeTEx XML (Profile: Line, Network, Full)
- Generate valid GTFS static feed (`.zip`)
- Support for routes, stops, trips, stop times, calendar, and shapes

## Requirements

- Python 3.10+
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

```bash
python main.py --input data/your_netex_file.xml --output output/gtfs.zip
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--input` | Path to the NeTEx XML file | — |
| `--output` | Path for the output GTFS zip | `output/gtfs.zip` |
| `--verbose` | Enable verbose logging | `False` |

## Input data

Place your NeTEx XML files inside the `data/` directory. They are excluded from version control via `.gitignore` due to file size.

## Output

The converter produces a standard GTFS static zip containing:

- `agency.txt`
- `stops.txt`
- `routes.txt`
- `trips.txt`
- `stop_times.txt`
- `calendar.txt` / `calendar_dates.txt`

## Project structure

```
netex2gtfs/
├── main.py          # Entry point
├── converter/       # Core conversion logic
│   ├── parser.py    # NeTEx XML parser
│   └── writer.py    # GTFS feed writer
├── data/            # Input NeTEx files (not tracked)
├── output/          # Generated GTFS feeds (not tracked)
└── requirements.txt
```

## Contributing

Pull requests are welcome. For major changes, please open an issue first.

## License

[MIT](LICENSE)