#!/usr/bin/env python3
"""
Fetch ENTSO-E Actual Total Load (A65) and Day-ahead Total Load Forecast (A65)
and store them separately.

Usage:
  python scripts/fetch_entsoe_load_and_forecast.py --areas DE_LU FR \
    --start-date 2023-01-01 --end-date 2025-12-13 --chunk-days 90

Outputs per area:
  - data/<AREA>/load_actual.csv
  - data/<AREA>/load_forecast.csv
    (includes `tso_day_ahead_forecast` and `tso_publication_time_utc` when
    available)

Notes:
  - Requires ENTSOE_TP_USERNAME + ENTSOE_TP_PASSWORD for the TP-FMS export files.
"""
import argparse
import calendar
from dataclasses import dataclass
import datetime as dt
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple
import xml.etree.ElementTree as ET
import zipfile

import requests

import pandas as pd

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Best-effort dotenv load so CLI can stay simple
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().strip().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

from src.data.io import (
    DATA_DIR,
    path_exists,
    read_csv_indexed,
    resolve_write_path,
    write_frame,
)


AREA_MAP = {
    "AL": "10YAL-KESH-----5",
    "BA": "10YBA-JPCC-----D",
    "CY": "10YCY-1001A0003J",
    "DE": "10Y1001A1001A83F",
    "DE_LU": "10Y1001A1001A82H",
    "GB": "10YGB----------A",
    "IE": "10YIE-1001A00010",
    "FR": "10YFR-RTE------C",
    "IT": "10Y1001A1001A73I",
    "ES": "10YES-REE------0",
    "PT": "10YPT-REN------W",
    "NL": "10YNL----------L",
    "BE": "10YBE----------2",
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
    "LU": "10YLU-CEGEDEL-NQ",
    "ME": "10YCS-CG-TSO---S",
    "MK": "10YMK-MEPSO----8",
    "MT": "10Y1001A1001A93C",
    "RS": "10YCS-SERBIATSOV",
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

ALT_CODES = {
    "DK1": "DK_1",
    "DK2": "DK_2",
    "NO1": "NO_1",
    "NO2": "NO_2",
    "NO3": "NO_3",
    "NO4": "NO_4",
    "NO5": "NO_5",
    "SE1": "SE_1",
    "SE2": "SE_2",
    "SE3": "SE_3",
    "SE4": "SE_4",
}

KEYCLOAK_URL = (
    "https://keycloak.tp.entsoe.eu/realms/tp/protocol/openid-connect/token"
)
LIST_FOLDER_URL = "https://fms.tp.entsoe.eu/listFolder"
DOWNLOAD_URL = "https://fms.tp.entsoe.eu/downloadFileContent"
CLIENT_ID = "tp-fms-public"
TOP_LEVEL_FOLDER = "TP_export"
ACTUAL_FOLDER = "/TP_export/ActualTotalLoad_6.1.A_r3/"
FORECAST_FOLDER = "/TP_export/DayAheadTotalLoadForecast_6.1.B_r3/"

AREA_COL_CANDIDATES = [
    "AreaCode",
    "BiddingZone",
    "BZN",
    "Area",
]
AREA_TYPE_COL_CANDIDATES = ["AreaTypeCode", "AreaType"]
TIME_COL_CANDIDATES = [
    "DateTime(UTC)",
    "DateTimeUTC",
    "DateTime",
    "TimeIntervalStart(UTC)",
    "TimeIntervalStart",
    "PeriodStartTime",
]
LOAD_VALUE_CANDIDATES = [
    "TotalLoadValue",
    "TotalLoad",
    "TotalLoad(MW)",
    "TotalLoadValue(MW)",
]
FORECAST_VALUE_CANDIDATES = [
    "DayAheadTotalLoadForecast",
    "TotalLoadForecast",
    "TotalLoadValue",
    "TotalLoad",
    "TotalLoad(MW)",
    "TotalLoadValue(MW)",
]
PUBLICATION_COL_CANDIDATES = [
    "PublicationDateTime",
    "PublicationTime",
    "CreatedDateTime",
    "CreationDateTime",
    "PublishDateTime",
    "UpdateTime(UTC)",
]
RESOLUTION_COL_CANDIDATES = ["ResolutionCode", "Resolution"]
AREA_DISPLAY_COL_CANDIDATES = ["AreaDisplayName", "AreaDisplay"]
AREA_MAP_COL_CANDIDATES = ["AreaMapCode", "AreaMap"]


def _parse_date(d):
    if isinstance(d, dt.date):
        return d
    return dt.datetime.strptime(str(d), "%Y-%m-%d").date()


def _chunk_ranges(
    start: dt.date, end: dt.date, chunk_days: int
) -> Iterable[Tuple[dt.date, dt.date]]:
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + dt.timedelta(days=chunk_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + dt.timedelta(days=1)


def _normalize_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.to_datetime(idx)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx


def _month_range(start: dt.date, end: dt.date) -> List[Tuple[int, int]]:
    ym: List[Tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        ym.append((y, m))
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return ym


def _guess_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = list(df.columns)
    col_map = {c.lower(): c for c in cols}
    for cand in candidates:
        key = cand.lower()
        if key in col_map:
            return col_map[key]
    for cand in candidates:
        needle = cand.lower()
        for col in cols:
            if needle in col.lower():
                return col
    return None


def _require_column(
    df: pd.DataFrame, candidates: List[str], label: str
) -> str:
    col = _guess_column(df, candidates)
    if not col:
        raise RuntimeError(f"Missing {label} column; found {list(df.columns)}")
    return col


def _parse_tsv_bytes(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw), sep="\t", encoding="utf-8")


def _maybe_unzip(raw: bytes) -> bytes:
    if not raw.startswith(b"PK"):
        return raw
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise RuntimeError("Zip file had no members")
        with zf.open(names[0]) as fh:
            return fh.read()


def _item_last_updated(item: Dict[str, Any]) -> str:
    return (
        item.get("lastUpdatedTimestamp")
        or item.get("lastUpdated")
        or item.get("lastUpdatedTime")
        or ""
    )


def _select_monthly_file(
    items: List[Dict[str, Any]], year: int, month: int
) -> Tuple[str, str]:
    patterns = [
        f"{year}_{month:02d}",
        f"{year}-{month:02d}",
        f"{year}{month:02d}",
    ]
    files = []
    for item in items:
        name = item.get("name") or ""
        if not any(p in name for p in patterns):
            continue
        item_type = (item.get("type") or "").upper()
        if item_type in {"FILE", "CSV", "ZIP", ""}:
            files.append(item)
    if not files:
        raise FileNotFoundError(
            f"No monthly file found for {year}-{month:02d}"
        )
    files.sort(key=_item_last_updated, reverse=True)
    picked = files[0]
    name = picked.get("name")
    last_ts = _item_last_updated(picked)
    if not name or not last_ts:
        raise RuntimeError(f"File missing metadata: {picked}")
    return name, last_ts


@dataclass(frozen=True)
class FmsItem:
    name: str
    type: str
    last_updated: Optional[str] = None


class EntsoeFmsClient:
    def __init__(
        self,
        username: str,
        password: str,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.username = username
        self.password = password
        self.s = session or requests.Session()
        self.token: Optional[str] = None

    def authenticate(self) -> None:
        r = self.s.post(
            KEYCLOAK_URL,
            data={
                "client_id": CLIENT_ID,
                "grant_type": "password",
                "username": self.username,
                "password": self.password,
            },
            timeout=30,
        )
        r.raise_for_status()
        self.token = r.json().get("access_token")
        if not self.token:
            raise RuntimeError("No access_token returned by Keycloak.")

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            raise RuntimeError(
                "Client not authenticated. Call authenticate()."
            )
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def list_folder(
        self, path: str, page_index: int = 0, page_size: int = 5000
    ) -> Dict[str, Any]:
        if not path.endswith("/"):
            path += "/"
        payload = {
            "path": path,
            "pageInfo": {"pageIndex": page_index, "pageSize": page_size},
            "sorterList": [{"key": "name", "ascending": True}],
        }
        r = self.s.post(
            LIST_FOLDER_URL,
            headers=self._headers(),
            data=json.dumps(payload),
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def download_file_content(
        self, folder: str, filename: str, last_update_ts: str
    ) -> bytes:
        if not folder.endswith("/"):
            folder += "/"
        payload = {
            "folder": folder,
            "filename": filename,
            "lastUpdateTimestamp": last_update_ts,
            "topLevelFolder": TOP_LEVEL_FOLDER,
            "downloadAsZip": False,
        }
        r = self.s.post(
            DOWNLOAD_URL,
            headers=self._headers(),
            data=json.dumps(payload),
            timeout=120,
        )
        r.raise_for_status()
        return r.content


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_first_text(elem: ET.Element, name: str) -> str | None:
    for child in elem.iter():
        if _strip_ns(child.tag) == name and child.text:
            return child.text.strip()
    return None


_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?)?$"
)


def _parse_duration(text: str) -> pd.Timedelta | None:
    if not text:
        return None
    match = _DURATION_RE.match(text)
    if not match:
        return None
    parts = {
        key: int(val) if val else 0 for key, val in match.groupdict().items()
    }
    return pd.Timedelta(
        days=parts["days"],
        hours=parts["hours"],
        minutes=parts["minutes"],
        seconds=parts["seconds"],
    )


def _parse_timestamp(text: str) -> pd.Timestamp | None:
    if not text:
        return None
    ts = pd.to_datetime(text, errors="coerce")
    if pd.isna(ts):
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _extract_publication_times(xml_text: str) -> pd.Series:
    root = ET.fromstring(xml_text)
    root_created_text = _find_first_text(root, "createdDateTime")
    root_created = (
        _parse_timestamp(root_created_text) if root_created_text else pd.NaT
    )

    timestamps = []
    publications = []

    for ts in root.iter():
        if _strip_ns(ts.tag) != "TimeSeries":
            continue
        ts_created_text = _find_first_text(ts, "createdDateTime")
        ts_created = (
            _parse_timestamp(ts_created_text)
            if ts_created_text
            else root_created
        )
        if pd.isna(ts_created):
            continue
        for period in ts.iter():
            if _strip_ns(period.tag) != "Period":
                continue
            start_text = _find_first_text(period, "start")
            resolution_text = _find_first_text(period, "resolution")
            if not start_text or not resolution_text:
                continue
            step = _parse_duration(resolution_text)
            if step is None or step <= pd.Timedelta(0):
                continue
            start_ts = _parse_timestamp(start_text)
            if pd.isna(start_ts):
                continue
            for point in period.iter():
                if _strip_ns(point.tag) != "Point":
                    continue
                pos_text = _find_first_text(point, "position")
                if not pos_text:
                    continue
                try:
                    position = int(pos_text)
                except ValueError:
                    continue
                ts_point = start_ts + step * (position - 1)
                timestamps.append(ts_point)
                publications.append(ts_created)

    if not timestamps:
        return pd.Series(dtype="datetime64[ns]")

    df = pd.DataFrame(
        {"timestamp": timestamps, "publication_time": publications}
    )
    df = df.dropna(subset=["timestamp", "publication_time"])
    if df.empty:
        return pd.Series(dtype="datetime64[ns]")
    return df.groupby("timestamp")["publication_time"].max().sort_index()


def _read_ts_csv(path: Path) -> pd.DataFrame:
    df = read_csv_indexed(path)
    df.index = pd.to_datetime(df.index, errors="coerce")
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    df = df[~df.index.isna()]
    return df


def _merge_timeseries(
    existing: pd.DataFrame, new: pd.DataFrame
) -> pd.DataFrame:
    combined = pd.concat([existing, new], axis=0)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return combined


def _resolve_area_code(area: str) -> str:
    return AREA_MAP.get(area, area)


def _prepare_fms_dataset(
    df: pd.DataFrame,
    area_codes: List[str],
    value_candidates: List[str],
    pub_candidates: Optional[List[str]] = None,
) -> Tuple[
    pd.DataFrame, Optional[str], Optional[str], str, str, Optional[str]
]:
    time_col = _require_column(df, TIME_COL_CANDIDATES, "time")
    value_col = _require_column(df, value_candidates, "load")
    area_col = _guess_column(df, AREA_COL_CANDIDATES)
    area_type_col = _guess_column(df, AREA_TYPE_COL_CANDIDATES)
    pub_col = (
        _guess_column(df, pub_candidates) if pub_candidates else None
    )

    keep = [
        c
        for c in [time_col, value_col, area_col, area_type_col, pub_col]
        if c
    ]
    df = df[keep].copy()

    if area_col:
        df = df[df[area_col].isin(area_codes)]

    df[time_col] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    if pub_col:
        df[pub_col] = pd.to_datetime(df[pub_col], utc=True, errors="coerce")

    return df, area_col, area_type_col, time_col, value_col, pub_col


def _subset_area(
    df: pd.DataFrame,
    area_col: Optional[str],
    area_type_col: Optional[str],
    code: str,
) -> pd.DataFrame:
    subset = df[df[area_col] == code] if area_col else df
    if not area_type_col or area_type_col not in df.columns:
        return subset
    area_type = subset[area_type_col].astype(str).str.upper()
    bzn = subset[area_type.eq("BZN")]
    return bzn if not bzn.empty else subset


def _build_area_frame(
    df: pd.DataFrame,
    time_col: str,
    value_col: str,
    value_name: str,
    pub_col: Optional[str] = None,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    work[time_col] = pd.to_datetime(work[time_col], utc=True, errors="coerce")
    if pub_col and pub_col in work.columns:
        work[pub_col] = pd.to_datetime(work[pub_col], utc=True, errors="coerce")
        work = work.sort_values([time_col, pub_col])
        work = work.drop_duplicates(subset=[time_col], keep="first")
    else:
        work = work.sort_values(time_col)
        work = work.drop_duplicates(subset=[time_col], keep="last")

    work = work[work[time_col].notna()]
    idx = work[time_col].dt.tz_convert("UTC").dt.tz_localize(None)
    out = pd.DataFrame(index=idx)
    out[value_name] = pd.to_numeric(
        work[value_col], errors="coerce"
    ).to_numpy()
    if pub_col and pub_col in work.columns:
        pub = work[pub_col].dt.tz_convert("UTC").dt.tz_localize(None)
        out["tso_publication_time_utc"] = pub.to_numpy()
    out = out[~out.index.isna()]
    out.index.name = "datetime"
    return out


def _parse_fms_datetime(series: pd.Series) -> pd.Series:
    text = series.astype(str)
    has_slash = text.str.contains("/", na=False)
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")
    if has_slash.any():
        out.loc[has_slash] = pd.to_datetime(
            text.loc[has_slash], utc=True, errors="coerce", dayfirst=True
        )
    if (~has_slash).any():
        out.loc[~has_slash] = pd.to_datetime(
            text.loc[~has_slash], utc=True, errors="coerce", dayfirst=False
        )
    return out


def _format_fms_datetime(series: pd.Series) -> pd.Series:
    return series.dt.strftime("%d/%m/%Y %H:%M")


def _prepare_raw_fms(
    df: pd.DataFrame, area_codes: List[str], value_candidates: List[str]
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    time_col = _require_column(df, TIME_COL_CANDIDATES, "time")
    value_col = _require_column(df, value_candidates, "load")
    area_col = _require_column(df, AREA_COL_CANDIDATES, "area")
    area_type_col = _guess_column(df, AREA_TYPE_COL_CANDIDATES)
    res_col = _guess_column(df, RESOLUTION_COL_CANDIDATES)
    display_col = _guess_column(df, AREA_DISPLAY_COL_CANDIDATES)
    map_col = _guess_column(df, AREA_MAP_COL_CANDIDATES)
    update_col = _guess_column(df, PUBLICATION_COL_CANDIDATES)

    keep = [
        c
        for c in [
            time_col,
            res_col,
            area_col,
            display_col,
            area_type_col,
            map_col,
            value_col,
            update_col,
        ]
        if c
    ]
    out = df[keep].copy()
    out = out[out[area_col].isin(area_codes)]

    meta = {
        "time_col": time_col,
        "value_col": value_col,
        "area_col": area_col,
        "area_type_col": area_type_col or "",
        "res_col": res_col or "",
        "display_col": display_col or "",
        "map_col": map_col or "",
        "update_col": update_col or "",
    }
    return out, meta


def _normalize_raw_fms(
    df: pd.DataFrame, time_col: str, update_col: Optional[str]
) -> pd.DataFrame:
    df = df.copy()
    df[time_col] = _parse_fms_datetime(df[time_col])
    if update_col and update_col in df.columns:
        df[update_col] = _parse_fms_datetime(df[update_col])
    df = df[df[time_col].notna()]
    if update_col and update_col in df.columns:
        df = df.sort_values([time_col, update_col])
        df = df.drop_duplicates(subset=[time_col], keep="first")
    else:
        df = df.sort_values(time_col)
        df = df.drop_duplicates(subset=[time_col], keep="last")
    return df


def _finalize_raw_fms(
    df: pd.DataFrame, time_col: str, update_col: Optional[str]
) -> pd.DataFrame:
    df = df.copy()
    df[time_col] = _format_fms_datetime(df[time_col])
    if update_col and update_col in df.columns:
        df[update_col] = _format_fms_datetime(df[update_col])
    return df


def _download_fms_month_df(
    client: EntsoeFmsClient,
    folder: str,
    items: List[Dict[str, Any]],
    year: int,
    month: int,
) -> pd.DataFrame:
    filename, last_ts = _select_monthly_file(items, year, month)
    raw = client.download_file_content(folder, filename, last_ts)
    return _parse_tsv_bytes(_maybe_unzip(raw))


def _fetch_area_load_and_forecast_fms(
    areas: List[str],
    start_date: dt.date,
    end_date: dt.date,
    merge_existing: bool,
    parquet: bool,
) -> None:
    user = os.getenv("ENTSOE_TP_USERNAME")
    pwd = os.getenv("ENTSOE_TP_PASSWORD")
    if not user or not pwd:
        raise SystemExit(
            "ENTSOE_TP_USERNAME and ENTSOE_TP_PASSWORD must be set."
        )

    client = EntsoeFmsClient(user, pwd)
    client.authenticate()

    actual_items = client.list_folder(ACTUAL_FOLDER).get(
        "contentItemList", []
    )
    forecast_items = client.list_folder(FORECAST_FOLDER).get(
        "contentItemList", []
    )
    if not actual_items or not forecast_items:
        raise RuntimeError("Empty FMS folder listing.")

    area_codes = {area: _resolve_area_code(area) for area in areas}
    code_list = list(area_codes.values())
    actual_frames: Dict[str, List[pd.DataFrame]] = {
        area: [] for area in areas
    }
    forecast_frames: Dict[str, List[pd.DataFrame]] = {
        area: [] for area in areas
    }
    raw_actual_frames: Dict[str, List[pd.DataFrame]] = {
        area: [] for area in areas
    }
    raw_forecast_frames: Dict[str, List[pd.DataFrame]] = {
        area: [] for area in areas
    }
    raw_actual_meta: Dict[str, str] | None = None
    raw_forecast_meta: Dict[str, str] | None = None

    for year, month in _month_range(start_date, end_date):
        print(f"[FMS] {year}-{month:02d}")
        try:
            actual_df = _download_fms_month_df(
                client, ACTUAL_FOLDER, actual_items, year, month
            )
        except FileNotFoundError as exc:
            print(f"  ⚠️  {exc}; skipping actual for {year}-{month:02d}")
            actual_df = pd.DataFrame()
        if not actual_df.empty:
            raw_actual_df, raw_meta = _prepare_raw_fms(
                actual_df, code_list, LOAD_VALUE_CANDIDATES
            )
            raw_actual_meta = raw_meta
            for area, code in area_codes.items():
                subset = _subset_area(
                    raw_actual_df,
                    raw_meta["area_col"],
                    raw_meta["area_type_col"] or None,
                    code,
                )
                if not subset.empty:
                    raw_actual_frames[area].append(subset)
            actual_df, area_col, area_type_col, t_col, v_col, _ = (
                _prepare_fms_dataset(
                    actual_df, code_list, LOAD_VALUE_CANDIDATES
                )
            )
            for area, code in area_codes.items():
                subset = _subset_area(
                    actual_df, area_col, area_type_col, code
                )
                frame = _build_area_frame(
                    subset, t_col, v_col, "actual_load"
                )
                if not frame.empty:
                    actual_frames[area].append(frame)
        else:
            actual_df = pd.DataFrame()

        try:
            forecast_df = _download_fms_month_df(
                client, FORECAST_FOLDER, forecast_items, year, month
            )
        except FileNotFoundError as exc:
            print(
                f"  ⚠️  {exc}; skipping forecast for {year}-{month:02d}"
            )
            forecast_df = pd.DataFrame()
        if not forecast_df.empty:
            raw_forecast_df, raw_meta_fc = _prepare_raw_fms(
                forecast_df, code_list, FORECAST_VALUE_CANDIDATES
            )
            raw_forecast_meta = raw_meta_fc
            for area, code in area_codes.items():
                subset = _subset_area(
                    raw_forecast_df,
                    raw_meta_fc["area_col"],
                    raw_meta_fc["area_type_col"] or None,
                    code,
                )
                if not subset.empty:
                    raw_forecast_frames[area].append(subset)
            forecast_df, f_area_col, f_area_type, ft_col, fv_col, pub_col = (
                _prepare_fms_dataset(
                    forecast_df,
                    code_list,
                    FORECAST_VALUE_CANDIDATES,
                    PUBLICATION_COL_CANDIDATES,
                )
            )
            for area, code in area_codes.items():
                subset = _subset_area(
                    forecast_df, f_area_col, f_area_type, code
                )
                frame = _build_area_frame(
                    subset,
                    ft_col,
                    fv_col,
                    "tso_day_ahead_forecast",
                    pub_col=pub_col,
                )
                if not frame.empty:
                    forecast_frames[area].append(frame)
        else:
            forecast_df = pd.DataFrame()

    start_ts = pd.Timestamp(start_date)
    end_exclusive = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    raw_start_ts = pd.Timestamp(start_date, tz="UTC")
    raw_end_exclusive = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(
        days=1
    )

    for area in areas:
        actual_list = actual_frames.get(area, [])
        forecast_list = forecast_frames.get(area, [])
        if not actual_list or not forecast_list:
            print(f"⚠️ No data for {area}, skipping")
            continue
        actual = pd.concat(actual_list).sort_index()
        forecast = pd.concat(forecast_list).sort_index()
        actual = actual[~actual.index.duplicated(keep="last")]
        forecast = forecast[~forecast.index.duplicated(keep="last")]
        actual = actual[
            (actual.index >= start_ts) & (actual.index < end_exclusive)
        ]
        forecast = forecast[
            (forecast.index >= start_ts) & (forecast.index < end_exclusive)
        ]

        area_dir = DATA_DIR / area
        actual_csv = resolve_write_path(area_dir / "load_actual.csv")
        forecast_csv = resolve_write_path(area_dir / "load_forecast.csv")
        to_write_actual = actual
        to_write_forecast = forecast

        if merge_existing:
            if path_exists(actual_csv):
                try:
                    old = _read_ts_csv(actual_csv)
                    to_write_actual = _merge_timeseries(old, actual)
                except Exception as e:
                    print(
                        f"⚠️  Failed to merge actual load for {area}: {e}"
                    )
            if path_exists(forecast_csv):
                try:
                    old = _read_ts_csv(forecast_csv)
                    to_write_forecast = _merge_timeseries(old, forecast)
                except Exception as e:
                    print(
                        f"⚠️  Failed to merge forecast load for {area}: {e}"
                    )

        write_frame(to_write_actual, actual_csv, index_label="datetime")
        write_frame(to_write_forecast, forecast_csv, index_label="datetime")
        print(
            f"✅ Saved actual -> {actual_csv} ({len(to_write_actual):,} rows)"
        )
        print(
            "✅ Saved forecast -> "
            f"{forecast_csv} ({len(to_write_forecast):,} rows)"
        )

        if parquet:
            write_frame(
                to_write_actual,
                resolve_write_path(area_dir / "load_actual.parquet"),
            )
            write_frame(
                to_write_forecast,
                resolve_write_path(area_dir / "load_forecast.parquet"),
            )

        if raw_actual_meta and raw_forecast_meta:
            raw_actual_list = raw_actual_frames.get(area, [])
            raw_forecast_list = raw_forecast_frames.get(area, [])
            if raw_actual_list:
                raw_actual = pd.concat(raw_actual_list).copy()
                time_col = raw_actual_meta["time_col"]
                update_col = raw_actual_meta.get("update_col") or None
                raw_actual = _normalize_raw_fms(
                    raw_actual, time_col, update_col
                )
                raw_actual = raw_actual[
                    (raw_actual[time_col] >= raw_start_ts)
                    & (raw_actual[time_col] < raw_end_exclusive)
                ]
                raw_actual = _finalize_raw_fms(
                    raw_actual, time_col, update_col
                )
                raw_path = resolve_write_path(
                    area_dir / "load_actual_raw.csv"
                )
                write_frame(raw_actual, raw_path, index=False)

            if raw_forecast_list:
                raw_forecast = pd.concat(raw_forecast_list).copy()
                time_col = raw_forecast_meta["time_col"]
                update_col = raw_forecast_meta.get("update_col") or None
                raw_forecast = _normalize_raw_fms(
                    raw_forecast, time_col, update_col
                )
                raw_forecast = raw_forecast[
                    (raw_forecast[time_col] >= raw_start_ts)
                    & (raw_forecast[time_col] < raw_end_exclusive)
                ]
                raw_forecast = _finalize_raw_fms(
                    raw_forecast, time_col, update_col
                )
                raw_path = resolve_write_path(
                    area_dir / "load_forecast_raw.csv"
                )
                write_frame(raw_forecast, raw_path, index=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE_LU")
    p.add_argument(
        "--areas", nargs="+", help="List of areas (overrides --area)"
    )
    p.add_argument("--start-date", default="2023-01-01")
    p.add_argument("--end-date", default=dt.date.today().isoformat())
    p.add_argument("--chunk-days", type=int, default=90)
    p.add_argument("--parquet", action="store_true", help="Also write Parquet")
    p.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge fetched window into existing CSVs instead of overwriting",
    )
    args = p.parse_args()

    tp_user = os.getenv("ENTSOE_TP_USERNAME")
    tp_pwd = os.getenv("ENTSOE_TP_PASSWORD")
    areas = args.areas if args.areas else [args.area]
    if not tp_user or not tp_pwd:
        raise SystemExit(
            "ENTSOE_TP_USERNAME and ENTSOE_TP_PASSWORD must be set."
        )
    _fetch_area_load_and_forecast_fms(
        areas,
        _parse_date(args.start_date),
        _parse_date(args.end_date),
        args.merge_existing,
        args.parquet,
    )


if __name__ == "__main__":
    main()
