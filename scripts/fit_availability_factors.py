#!/usr/bin/env python3
"""Fit plant availability factors from ENTSO-E actual generation per unit (A73).

This script fetches A73 data, aggregates mean output per unit, and produces
availability factors by dividing mean MW by OPSD nameplate capacity.

Outputs a CSV with columns:
  eic_code, availability_factor, mean_generation_mw, capacity_mw, hours_observed
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import io
import os
from pathlib import Path
import re
from typing import Dict, Iterable, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

import pandas as pd

from src.data.io import DATA_DIR, resolve_write_path, write_frame

from src.power_model.plants import PlantStack


AREA_MAP = {
    "DE_LU": "10Y1001A1001A82H",
    "FR": "10YFR-RTE------C",
    "IT": "10Y1001A1001A73I",
    "ES": "10YES-REE------0",
    "PT": "10YPT-REN------W",
    "NL": "10YNL----------L",
    "BE": "10YBE----------2",
    "GB": "10YGB----------A",
    "IE": "10YIE-1001A00010",
    "NI": "10Y1001A1001A016",
    "CH": "10YCH-SWISSGRIDZ",
    "AT": "10YAT-APG------L",
    "PL": "10YPL-AREA-----S",
    "CZ": "10YCZ-CEPS-----N",
    "SK": "10YSK-SEPS-----K",
    "HU": "10YHU-MAVIR----U",
    "RO": "10YRO-TEL------P",
    "BG": "10YCA-BULGARIA-R",
    "SI": "10YSI-ELES-----O",
    "HR": "10YHR-HEP------M",
    "GR": "10YGR-HTSO-----Y",
    "DK1": "10YDK-1--------W",
    "DK2": "10YDK-2--------M",
    "FI": "10YFI-1--------U",
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
    "NO1": "10YNO-1--------2",
    "NO2": "10YNO-2--------T",
    "NO3": "10YNO-3--------J",
    "NO4": "10YNO-4--------9",
    "NO5": "10Y1001A1001A48H",
    "LT": "10YLT-1001A0008Q",
    "LV": "10YLV-1001A00074",
    "EE": "10Y1001A1001A39I",
}


def _parse_date(date_or_str) -> dt.date:
    if isinstance(date_or_str, dt.date):
        return date_or_str
    return dt.datetime.strptime(str(date_or_str), "%Y-%m-%d").date()


def _chunk_date_ranges(
    start_date: dt.date, end_date: dt.date, chunk_days: int
) -> Iterable[Tuple[dt.date, dt.date]]:
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + dt.timedelta(days=chunk_days - 1), end_date)
        yield cursor, chunk_end
        cursor = chunk_end + dt.timedelta(days=1)


def _load_token() -> str:
    token = os.getenv("ENTSOE_API_TOKEN")
    if token:
        return token

    cfg_path = Path(__file__).parents[1] / "src" / "config.yaml"
    if cfg_path.exists():
        text = cfg_path.read_text(encoding="utf-8")
        match = re.search(r'api_key:\s*"([^"]+)"', text)
        if match:
            return match.group(1)

    env_path = Path(__file__).parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ENTSOE_API_TOKEN="):
                return line.split("=", 1)[1].strip()

    raise SystemExit(
        "ENTSOE_API_TOKEN not found in env, .env, or src/config.yaml"
    )


def _resolution_hours(text: str) -> float:
    if not text:
        return 0.0
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
    if not match:
        return 0.0
    hours = float(match.group(1) or 0)
    minutes = float(match.group(2) or 0)
    return hours + minutes / 60.0


def _find_text(elem: ET.Element, suffix: str) -> str | None:
    for child in elem.iter():
        if child.tag.endswith(suffix):
            return child.text
    return None


def _parse_ack(xml_bytes: bytes) -> str | None:
    if len(xml_bytes) > 5000:
        return None
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    if not root.tag.endswith("Acknowledgement_MarketDocument"):
        return None
    reason = root.find(".//{*}Reason")
    text = reason.findtext("{*}text") if reason is not None else None
    return text or "Acknowledgement response"


def _fetch_generation_xml(
    api_token: str, area_code: str, start_date: dt.date, end_date: dt.date
) -> bytes:
    url = "https://web-api.tp.entsoe.eu/api"
    start_ts = f"{start_date.strftime('%Y%m%d')}0000"
    end_ts = (end_date + dt.timedelta(days=1)).strftime("%Y%m%d") + "0000"
    params = {
        "securityToken": api_token,
        "documentType": "A73",
        "processType": "A16",
        "in_Domain": area_code,
        "periodStart": start_ts,
        "periodEnd": end_ts,
    }
    query = urlencode(params)
    req = Request(f"{url}?{query}", headers={"User-Agent": "python"})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read()
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(
            f"ENTSO-E API request failed: {e.code} {detail[:500]}"
        )


def _accumulate_totals(
    xml_bytes: bytes,
    energy_mwh: Dict[str, float],
    hours: Dict[str, float],
    *,
    clip_negative: bool = True,
) -> int:
    ack_reason = _parse_ack(xml_bytes)
    if ack_reason:
        print(f"  Skipping chunk: {ack_reason}")
        return 0

    series_count = 0
    context = ET.iterparse(io.BytesIO(xml_bytes), events=("end",))
    for _, elem in context:
        if not elem.tag.endswith("TimeSeries"):
            continue
        series_count += 1
        unit_id = _find_text(elem, "registeredResource.mRID")
        if not unit_id:
            elem.clear()
            continue
        unit_id = unit_id.strip()
        for period in elem.iter():
            if not period.tag.endswith("Period"):
                continue
            res_text = _find_text(period, "resolution")
            res_hours = _resolution_hours(res_text or "")
            if res_hours <= 0:
                continue
            for point in period.iter():
                if not point.tag.endswith("Point"):
                    continue
                qty_text = _find_text(point, "quantity")
                if qty_text is None:
                    continue
                try:
                    qty = float(qty_text)
                except ValueError:
                    continue
                if clip_negative and qty < 0:
                    qty = 0.0
                energy_mwh[unit_id] += qty * res_hours
                hours[unit_id] += res_hours
        elem.clear()
    return series_count


def _build_plant_lookup(area: str) -> pd.DataFrame:
    stack = PlantStack.from_opsd(
        countries=None,
        bidding_zones=(area,),
        min_capacity_mw=0.0,
        include_renewables=False,
    )
    plants = stack.plants.copy()
    plants["eic_code"] = plants["eic_code"].astype(str).str.strip()
    plants = plants.replace({"eic_code": {"": pd.NA, "nan": pd.NA}})
    plants = plants.dropna(subset=["eic_code"])
    plants = plants.drop_duplicates(subset=["eic_code"], keep="first")
    return plants.set_index("eic_code")


def _fit_availability(
    plants: pd.DataFrame,
    energy_mwh: Dict[str, float],
    hours: Dict[str, float],
    *,
    clip_min: float,
    clip_max: float,
    min_hours: float,
) -> pd.DataFrame:
    rows = []
    for unit_id, total_mwh in energy_mwh.items():
        obs_hours = hours.get(unit_id, 0.0)
        if obs_hours <= 0 or obs_hours < min_hours:
            continue
        if unit_id not in plants.index:
            continue
        capacity = float(plants.at[unit_id, "capacity_mw"])
        if capacity <= 0:
            continue
        mean_mw = total_mwh / obs_hours
        availability = mean_mw / capacity
        availability = max(clip_min, min(clip_max, availability))
        row = {
            "eic_code": unit_id,
            "availability_factor": availability,
            "mean_generation_mw": mean_mw,
            "capacity_mw": capacity,
            "hours_observed": obs_hours,
            "name": plants.at[unit_id, "name"],
            "fuel": plants.at[unit_id, "fuel"],
            "stack_type": plants.at[unit_id, "stack_type"],
            "bidding_zone": plants.at[unit_id, "bidding_zone"],
            "country": plants.at[unit_id, "country"],
        }
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fit availability factors from ENTSO-E A73 unit generation."
    )
    parser.add_argument("--area", default=None, help="Single area (e.g., FR)")
    parser.add_argument(
        "--areas", nargs="+", help="List of areas (overrides --area)"
    )
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--chunk-days", type=int, default=7)
    parser.add_argument(
        "--min-hours",
        type=float,
        default=24.0,
        help="Minimum observed hours required per unit",
    )
    parser.add_argument("--clip-min", type=float, default=0.0)
    parser.add_argument("--clip-max", type=float, default=1.2)
    parser.add_argument(
        "--output",
        help="Single-area output CSV (defaults to data/<AREA>/availability_factors.csv)",
    )
    args = parser.parse_args()

    token = _load_token()

    if args.areas:
        areas = args.areas
    else:
        areas = [args.area] if args.area else []
    if not areas:
        cfg_path = Path(__file__).parents[1] / "src" / "config.yaml"
        if cfg_path.exists():
            text = cfg_path.read_text(encoding="utf-8")
            match = re.search(r"default_area:\s*([A-Z0-9_]+)", text)
            if match:
                areas = [match.group(1)]
    if not areas:
        raise SystemExit("No areas specified; use --area or --areas.")

    end_date = _parse_date(args.end_date) if args.end_date else dt.date.today()
    start_date = (
        _parse_date(args.start_date)
        if args.start_date
        else end_date - dt.timedelta(days=30)
    )

    for area in areas:
        area_code = AREA_MAP.get(area, area)
        print(f"\n=== {area} ({area_code}) ===")

        energy_mwh: Dict[str, float] = defaultdict(float)
        hours: Dict[str, float] = defaultdict(float)

        ranges = list(
            _chunk_date_ranges(
                start_date, end_date, max(int(args.chunk_days), 1)
            )
        )
        print(f"Planned chunks: {len(ranges)} ({start_date} -> {end_date})")

        for idx, (cs, ce) in enumerate(ranges, start=1):
            print(f"  Chunk {idx}/{len(ranges)}: {cs} -> {ce}")
            xml_bytes = _fetch_generation_xml(token, area_code, cs, ce)
            series_count = _accumulate_totals(
                xml_bytes, energy_mwh, hours, clip_negative=True
            )
            print(f"    TimeSeries parsed: {series_count}")

        if not energy_mwh:
            print("  No unit-level generation data returned. Skipping.")
            continue

        plants = _build_plant_lookup(area)
        out = _fit_availability(
            plants,
            energy_mwh,
            hours,
            clip_min=args.clip_min,
            clip_max=args.clip_max,
            min_hours=args.min_hours,
        )

        if out.empty:
            print("  No matched plants with availability factors.")
            continue

        area_dir = DATA_DIR / area
        out_path = (
            args.output
            if (len(areas) == 1 and args.output)
            else area_dir / "availability_factors.csv"
        )
        out_path = resolve_write_path(out_path)
        out = out.sort_values("availability_factor", ascending=False)
        write_frame(out, out_path, index=False)
        matched = out["eic_code"].nunique()
        print(f"  ✅ Saved {matched} availability factors to {out_path}")


if __name__ == "__main__":
    main()
