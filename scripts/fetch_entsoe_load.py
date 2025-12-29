#!/usr/bin/env python3
"""
Fetch ENTSO-E load using TP-FMS export (no entsoe-py).

Usage:
  python scripts/fetch_entsoe_load.py --areas DE_LU FR ES \
    --start-date 2023-01-01 --end-date 2025-12-12

Requires ENTSOE_TP_USERNAME and ENTSOE_TP_PASSWORD in env or .env.
Writes per area:
  - load_actual.csv
  - load_forecast.csv
  - load_actual_raw.csv / load_forecast_raw.csv
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except Exception:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from scripts.fetch_entsoe_load_and_forecast import (
    _fetch_area_load_and_forecast_fms,
    _parse_date,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE_LU")
    p.add_argument(
        "--areas", nargs="+", help="List of areas (overrides --area)"
    )
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--parquet", action="store_true")
    p.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge fetched window into existing CSVs instead of overwriting",
    )
    args = p.parse_args()

    tp_user = os.getenv("ENTSOE_TP_USERNAME")
    tp_pwd = os.getenv("ENTSOE_TP_PASSWORD")
    if not tp_user or not tp_pwd:
        raise SystemExit(
            "ENTSOE_TP_USERNAME and ENTSOE_TP_PASSWORD must be set."
        )

    areas = args.areas if args.areas else [args.area]
    _fetch_area_load_and_forecast_fms(
        areas,
        _parse_date(args.start_date),
        _parse_date(args.end_date),
        args.merge_existing,
        args.parquet,
    )


if __name__ == "__main__":
    main()
