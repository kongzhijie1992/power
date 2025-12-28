"""GFS ingestion helpers.

This module provides functions to download GFS GRIB2 files from NOAA's NOMADS server
and (optionally) parse them using xarray + cfgrib if those libraries are installed.

Notes:
- GRIB parsing requires external dependencies (`cfgrib` + `ecCodes`) which must be
  installed on the host. If not available, this module will still download files for later parsing.
"""

import logging
from pathlib import Path
import datetime as dt
import os
import tempfile
import requests
import xarray as xr

logger = logging.getLogger(__name__)

BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod"


def _make_gfs_filename(
    run_dt: dt.datetime,
    hour_str: int = 0,
    resolution: str = "0p25",
    fh: int = 0,
):
    # example file: gfs.t00z.pgrb2.0p25.f000
    hh = run_dt.hour
    return f"gfs.t{hh:02d}z.pgrb2.{resolution}.f{fh:03d}"


def _make_gfs_url(run_dt: dt.datetime, resolution: str = "0p25", fh: int = 0):
    ymd = run_dt.strftime("%Y%m%d")
    hh = run_dt.hour
    fname = _make_gfs_filename(
        run_dt, hour_str=hh, resolution=resolution, fh=fh
    )
    # path pattern used by NOMADS
    return f"{BASE_URL}/gfs.{ymd}/{hh:02d}/atmos/{fname}"


def download_gfs_analysis(
    run_dt: dt.datetime = None,
    resolution: str = "0p25",
    fh: int = 0,
    dest_dir: Path = None,
):
    """Download a single GFS GRIB file (analysis or forecast hour).

    Returns local Path to the downloaded file.
    """
    run_dt = run_dt or dt.datetime.utcnow()
    if dest_dir is None:
        base = os.getenv("GFS_CACHE_DIR")
        root = (
            Path(base) if base else Path(tempfile.gettempdir()) / "power_gfs"
        )
        dest_dir = root / run_dt.strftime("%Y%m%d") / f"{run_dt.hour:02d}"
    dest_dir = Path(dest_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    url = _make_gfs_url(run_dt, resolution=resolution, fh=fh)
    # NOAA files may have extensions or be gzip; try common variants
    candidates = [url, url + ".grib2", url + ".grb2", url + ".grb2.gz"]
    for c in candidates:
        try:
            r = requests.get(c, stream=True, timeout=30)
            if r.status_code == 200:
                fname = c.split("/")[-1]
                out = dest_dir / fname
                with open(out, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                logger.info("Downloaded %s -> %s", c, out)
                return out
        except Exception as e:
            logger.debug("Download failed for %s: %s", c, e)
    raise RuntimeError(f"Failed to download GFS file for run {run_dt} fh {fh}")


def parse_grib_to_xarray(path: Path, filter_by_keys=None):
    """Parse a GRIB2 file into an xarray.Dataset using cfgrib engine.

    Returns xarray Dataset. If cfgrib/xarray not available, raises ImportError.
    """
    try:
        ds = xr.open_dataset(
            path, engine="cfgrib", backend_kwargs={"errors": "ignore"}
        )
        if filter_by_keys:
            # user may filter dataset variables afterwards
            pass
        return ds
    except Exception as e:
        logger.error("Parsing GRIB failed (cfgrib/ecCodes required): %s", e)
        raise


def fetch_and_extract_point(
    lat: float,
    lon: float,
    run_dt: dt.datetime = None,
    fh: int = 0,
    varnames=None,
):
    """Download GFS file for `run_dt` and `fh`, parse it and extract nearest-gridpoint timeseries for `varnames`.

    - `varnames` example: ['2t' (2m temp), '10u', '10v', 'dswrf'] depending on GRIB keys.
    - Requires `xarray` + `cfgrib`.
    """
    import pandas as pd

    run_dt = (
        run_dt
        or pd.Timestamp.utcnow()
        .replace(minute=0, second=0, microsecond=0)
        .to_pydatetime()
    )
    path = download_gfs_analysis(run_dt, fh=fh)
    ds = parse_grib_to_xarray(path)
    # naive nearest neighbour extraction
    # xarray coords names vary; try common lat/lon names
    lat_name = (
        "latitude"
        if "latitude" in ds.coords
        else ("lat" if "lat" in ds.coords else None)
    )
    lon_name = (
        "longitude"
        if "longitude" in ds.coords
        else ("lon" if "lon" in ds.coords else None)
    )
    if lat_name is None or lon_name is None:
        raise RuntimeError(
            "Unable to locate lat/lon coordinates in GRIB dataset"
        )
    # compute absolute difference and find nearest idx
    absdiff = (abs(ds[lat_name] - lat)).argmin().item(), (
        abs(ds[lon_name] - lon)
    ).argmin().item()
    ilat, ilon = absdiff
    out = {}
    for v in varnames or []:
        if v in ds:
            data = ds[v].isel({lat_name: ilat, lon_name: ilon})
            out[v] = data.to_series()
    return out
