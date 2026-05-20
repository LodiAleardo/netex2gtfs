import argparse
import logging
import sys
from pathlib import Path

from converter import parser, writer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert NeTEx XML to GTFS static feed.")
    p.add_argument("--input", required=True, type=Path, help="Path to NeTEx XML file")
    p.add_argument("--output", default=Path("output/gtfs.zip"), type=Path, help="Output GTFS zip path")
    p.add_argument("--extend", type=int, default=0, help="Extend feed to this date by N week(s)")
    p.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not args.input.exists():
        logging.error("Input file not found: %s", args.input)
        sys.exit(1)

    writer.write(
        parser.parse(str(args.input), extend_calendar_weeks=args.extend),
        args.output)


if __name__ == "__main__":
    main()
