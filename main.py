import argparse
import logging
import sys
from pathlib import Path

from converter import parser, writer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert NeTEx XML to GTFS static feed.")
    p.add_argument("--input", required=True, type=Path, help="Path to NeTEx XML file")
    p.add_argument("--output", default=Path("output/gtfs.zip"), type=Path, help="Output GTFS zip path")
    p.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    p.add_argument(
        "--extend-calendar-weeks",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Expand the weekly service pattern for N weeks beyond the feed end date "
            "for services whose schedule runs through the end of the feed period "
            "(mirrors the extend_calendar behaviour in calendar.txt-based feeds). "
            "0 disables (default)."
        ),
    )
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

    data = parser.parse(str(args.input), extend_calendar_weeks=args.extend_calendar_weeks)
    writer.write(data, args.output)


if __name__ == "__main__":
    main()
