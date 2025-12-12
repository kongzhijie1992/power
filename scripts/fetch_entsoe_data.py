#!/usr/bin/env python3
"""Fetch real ENTSO-E day-ahead prices using the API token.

Usage:
  # Pull a custom range (recommended)
  python scripts/fetch_entsoe_data.py --area DE_LU --start-date 2023-01-01 --end-date 2024-12-31 --chunk-days 90

  # Fetch multiple areas in one go (saves per-area CSVs)
  python scripts/fetch_entsoe_data.py --areas DE_LU FR ES --start-date 2023-01-01 --end-date 2024-12-31 --chunk-days 90

  # Or pull trailing N days (legacy behavior)
  python scripts/fetch_entsoe_data.py --area DE_LU --days 90

Requires ENTSOE_API_TOKEN environment variable or .env file for price calls.
You can run with --weather-only (no token) to fetch Open-Meteo weather for the same window.

Creates:
 - data/<AREA>/day_ahead_real.csv (hourly prices from ENTSO-E API, column 'value')
 - data/weather/<area>_weather.csv (hourly weather from Open-Meteo, no key required)
"""
import argparse
import os
from pathlib import Path
import datetime as dt
from typing import Iterable, Tuple

import requests
import pandas as pd

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback: read .env manually
    env_path = Path(__file__).parents[1] / '.env'
    if env_path.exists():
        for line in env_path.read_text().strip().split('\n'):
            if '=' in line and not line.startswith('#'):
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()


def _parse_date(date_or_str):
    """Return a date object from either a date/datetime or YYYY-MM-DD string."""
    if isinstance(date_or_str, dt.date):
        return date_or_str
    return dt.datetime.strptime(str(date_or_str), "%Y-%m-%d").date()


def _chunk_date_ranges(start_date: dt.date, end_date: dt.date, chunk_days: int) -> Iterable[Tuple[dt.date, dt.date]]:
    """Yield (start, end) date tuples covering the inclusive range in fixed-size chunks."""
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + dt.timedelta(days=chunk_days - 1), end_date)
        yield cursor, chunk_end
        cursor = chunk_end + dt.timedelta(days=1)


def fetch_entsoe_prices(api_token, area_code, start_date, end_date, out_csv_path=None):
    """Fetch day-ahead prices from ENTSO-E API and return a DataFrame."""
    # ENTSO-E area code mappings (EIC codes)
    area_map = {
        'DE_LU': '10Y1001A1001A82H',  # Germany/Luxembourg
        'FR': '10YFR-RTE------C',      # France
        'IT': '10Y1001A1001A73I',      # Italy (A44 area EIC)
        'ES': '10YES-REE------0',      # Spain
        'PT': '10YPT-REN------W',      # Portugal
        'NL': '10YNL----------L',      # Netherlands
        'BE': '10YBE----------2',      # Belgium
        'GB': '10YGB----------A',      # Great Britain
        'IE': '10YIE-1001A00010',      # Ireland (SEM)
        'NI': '10Y1001A1001A016',      # Northern Ireland
        'CH': '10YCH-SWISSGRIDZ',      # Switzerland
        'AT': '10YAT-APG------L',      # Austria
        'PL': '10YPL-AREA-----S',      # Poland
        'CZ': '10YCZ-CEPS-----N',      # Czech Republic
        'SK': '10YSK-SEPS-----K',      # Slovakia
        'HU': '10YHU-MAVIR----U',      # Hungary
        'RO': '10YRO-TEL------P',      # Romania
        'BG': '10YCA-BULGARIA-R',      # Bulgaria
        'SI': '10YSI-ELES-----O',      # Slovenia
        'HR': '10YHR-HEP------M',      # Croatia
        'GR': '10YGR-HTSO-----Y',      # Greece
        'DK1': '10YDK-1--------W',     # Denmark West
        'DK2': '10YDK-2--------M',     # Denmark East
        'FI': '10YFI-1--------U',      # Finland
        'SE1': '10Y1001A1001A44P',     # Sweden SE1
        'SE2': '10Y1001A1001A45N',     # Sweden SE2
        'SE3': '10Y1001A1001A46L',     # Sweden SE3
        'SE4': '10Y1001A1001A47J',     # Sweden SE4
        'NO1': '10YNO-1--------2',     # Norway NO1
        'NO2': '10YNO-2--------T',     # Norway NO2
        'NO3': '10YNO-3--------J',     # Norway NO3
        'NO4': '10YNO-4--------9',     # Norway NO4
        'NO5': '10Y1001A1001A48H',     # Norway NO5
        'LT': '10YLT-1001A0008Q',      # Lithuania
        'LV': '10YLV-1001A00074',      # Latvia
        'EE': '10Y1001A1001A39I',      # Estonia
    }
    
    eic_code = area_map.get(area_code, area_code)  # use provided code as fallback
    
    # ENTSO-E API endpoint for day-ahead market prices
    url = "https://web-api.tp.entsoe.eu/api"
    
    # Convert dates to ENTSO-E format (YYYYMMDDHHMM). periodEnd is exclusive, so add +1 day at 00:00.
    start_date_obj = _parse_date(start_date)
    end_date_obj = _parse_date(end_date)
    start_ts = f"{start_date_obj.strftime('%Y%m%d')}0000"
    end_ts = (end_date_obj + dt.timedelta(days=1)).strftime("%Y%m%d") + "0000"
    
    params = {
        'securityToken': api_token,
        'documentType': 'A44',  # Day-ahead prices
        'In_Domain': eic_code,
        'Out_Domain': eic_code,
        'periodStart': start_ts,
        'periodEnd': end_ts,
    }
    
    print(f"Fetching ENTSO-E data for {area_code} ({eic_code}) from {start_date_obj} to {end_date_obj}...")
    print(f"Requesting: {url}")
    print(f"Params: periodStart={params['periodStart']} periodEnd={params['periodEnd']} In_Domain={params['In_Domain']}")
    
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error {r.status_code}: {r.text[:500]}")
        raise SystemExit(f"ENTSO-E API request failed: {e}")
    except requests.exceptions.RequestException as e:
        raise SystemExit(f"ENTSO-E API request failed: {e}")
    
    # Parse XML response (ENTSO-E uses XML)
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(r.content)
        # Extract price points from XML
        prices = []
        timestamps = []
        
        # Namespace-agnostic search helpers
        def _iter_by_suffix(tag_suffix):
            return [elem for elem in root.iter() if elem.tag.endswith(tag_suffix)]

        timeseries = _iter_by_suffix('TimeSeries')
        
        for ts in timeseries:
            period_candidates = [elem for elem in ts.iter() if elem.tag.endswith('Period')]
            period = period_candidates[0] if period_candidates else None
            
            if period is not None:
                time_interval_candidates = [elem for elem in period.iter() if elem.tag.endswith('timeInterval')]
                time_interval = time_interval_candidates[0] if time_interval_candidates else None
                
                start_elem = None
                if time_interval is not None:
                    for child in time_interval.iter():
                        if child.tag.endswith('start'):
                            start_elem = child
                            break
                
                if start_elem is not None:
                    start_time = pd.to_datetime(start_elem.text, utc=True)
                    
                    points = [elem for elem in period.iter() if elem.tag.endswith('Point')]
                    
                    for i, point in enumerate(points):
                        price_elem = None
                        for child in point:
                            if child.tag.endswith('price.amount'):
                                price_elem = child
                                break
                        
                        if price_elem is not None and price_elem.text:
                            price = float(price_elem.text)
                            ts_point = start_time + dt.timedelta(hours=i)
                            timestamps.append(ts_point)
                            prices.append(price)
        
        if not prices:
            print("Response body (truncated):")
            print(r.text[:1000])
            raise SystemExit("No price data found in ENTSO-E response. Check area code and date range.")
        
        # Create DataFrame
        df = pd.DataFrame({'value': prices}, index=pd.to_datetime(timestamps, utc=True))
        df.index.name = 'datetime'
        
        if out_csv_path:
            out_path = Path(out_csv_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out_path)
            print(f"Saved {len(df)} hours of real ENTSO-E prices to {out_path}")
        
        return df
        
    except ET.ParseError as e:
        print(f"Failed to parse ENTSO-E response: {e}")
        print(f"Response (truncated): {r.text[:1000]}")
        raise SystemExit("Invalid ENTSO-E response format")


def download_open_meteo(lat, lon, start_date, end_date, out_csv_path):
    """Download weather data from Open-Meteo archive (no API key required)."""
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}&start_date={start_date}&end_date={end_date}"
        "&hourly=windspeed_10m,shortwave_radiation&timezone=UTC"
    )
    print(f"Requesting weather from Open-Meteo: {url}")
    
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise SystemExit(f"Open-Meteo request failed: {e}")
    
    j = r.json()
    if 'hourly' not in j:
        raise SystemExit('Open-Meteo returned no hourly data')
    
    hourly = j['hourly']
    df = pd.DataFrame(hourly)
    df['time'] = pd.to_datetime(df['time'])
    df = df.set_index('time')
    
    out_dir = Path(out_csv_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv_path)
    print(f"Saved weather to {out_csv_path}")
    return out_csv_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--area', default='DE_LU', help='ENTSO-E area code (e.g., DE_LU, FR, IT, ES)')
    p.add_argument('--areas', nargs='+', help='List of ENTSO-E area codes (overrides --area)')
    p.add_argument('--lat', type=float, default=52.52, help='Latitude for weather data (Germany)')
    p.add_argument('--lon', type=float, default=13.405, help='Longitude for weather data (Germany)')
    p.add_argument('--days', type=int, default=90, help='Number of days to fetch (historical, used if no explicit dates)')
    p.add_argument('--start-date', help='Start date (YYYY-MM-DD). If set, overrides --days.')
    p.add_argument('--end-date', help='End date (YYYY-MM-DD). If set, overrides --days.')
    p.add_argument('--chunk-days', type=int, default=90, help='Chunk size in days for API calls (prevents 400 errors on long ranges)')
    p.add_argument('--output', help='Output CSV path for prices (single-area only)', default=None)
    p.add_argument('--no-weather', action='store_true', help='Skip weather download')
    p.add_argument('--skip-price', action='store_true', help='Skip price download (useful for weather-only updates)')
    p.add_argument('--weather-only', action='store_true', help='Alias for --skip-price (fetch only weather)')
    args = p.parse_args()

    api_token = os.getenv('ENTSOE_API_TOKEN')
    if not api_token and not (args.skip_price or args.weather_only):
        raise SystemExit(
            'ENTSOE_API_TOKEN not set. Please:\n'
            '  1. Set environment variable: export ENTSOE_API_TOKEN=<your-token>\n'
            '  2. Or add to .env file: ENTSOE_API_TOKEN=<your-token>\n'
            'Or rerun with --weather-only / --skip-price if you only need Open-Meteo weather.'
        )

    areas = args.areas if args.areas else [args.area]
    if len(areas) > 1 and args.output:
        print("⚠️  Ignoring --output because multiple areas were specified; using per-area defaults.")

    # weather-only alias
    if args.weather_only:
        args.skip_price = True

    if args.start_date and args.end_date:
        start_date = _parse_date(args.start_date)
        end_date = _parse_date(args.end_date)
    else:
        end_date = dt.date.today() - dt.timedelta(days=1)
        start_date = end_date - dt.timedelta(days=args.days - 1)

    # Prices: fetch real ENTSO-E data (chunked)
    # Precompute chunks once
    ranges = list(_chunk_date_ranges(start_date, end_date, max(args.chunk_days, 1)))
    print(f"\nPlanned API calls per area: {len(ranges)} chunk(s)")

    # Default lat/lon per area (fallback to provided lat/lon)
    default_lat_lon = {
        'DE_LU': (52.52, 13.405),
        'FR': (48.8566, 2.3522),
        'ES': (40.4168, -3.7038),
        'IT': (41.9028, 12.4964),
        'NL': (52.3676, 4.9041),
        'BE': (50.8503, 4.3517),
        'PT': (38.7223, -9.1393),
        'CH': (46.9480, 7.4474),
        'AT': (48.2082, 16.3738),
        'PL': (52.2297, 21.0122),
        'CZ': (50.0755, 14.4378),
        'SK': (48.1486, 17.1077),
        'HU': (47.4979, 19.0402),
        'RO': (44.4268, 26.1025),
        'BG': (42.6977, 23.3219),
        'SI': (46.0569, 14.5058),
        'HR': (45.8150, 15.9819),
        'GR': (37.9838, 23.7275),
        'DK1': (55.6761, 12.5683),
        'DK2': (55.6761, 12.5683),
        'FI': (60.1699, 24.9384),
        'SE1': (65.5848, 22.1567),
        'SE2': (63.8258, 20.2630),
        'SE3': (59.3293, 18.0686),
        'SE4': (55.60498, 13.0038),
        'NO1': (59.9139, 10.7522),
        'NO2': (58.9690, 5.7320),
        'NO3': (63.4305, 10.3951),
        'NO4': (69.6492, 18.9553),
        'NO5': (60.39299, 5.32415),
        'LT': (54.6872, 25.2797),
        'LV': (56.9496, 24.1052),
        'EE': (59.4370, 24.7536),
    }

    for area in areas:
        print(f"\n===== AREA: {area} =====")
        data_dir = Path(__file__).parents[1] / 'data' / area
        data_dir.mkdir(parents=True, exist_ok=True)
        price_csv = Path(args.output) if (len(areas) == 1 and args.output) else data_dir / 'day_ahead_real.csv'

        if not args.skip_price:
            combined_frames = []
            for idx, (chunk_start, chunk_end) in enumerate(ranges, start=1):
                print(f"\nChunk {idx}/{len(ranges)}: {chunk_start} → {chunk_end}")
                df_chunk = fetch_entsoe_prices(api_token, area, chunk_start, chunk_end)
                combined_frames.append(df_chunk)

            combined = pd.concat(combined_frames, axis=0).sort_index()
            combined = combined[~combined.index.duplicated(keep='first')]

            # Clamp to requested date range (inclusive) in UTC
            start_ts = pd.Timestamp(start_date).tz_localize('UTC')
            end_ts = pd.Timestamp(end_date + dt.timedelta(days=1)).tz_localize('UTC') - pd.Timedelta(hours=1)
            combined = combined[(combined.index >= start_ts) & (combined.index <= end_ts)]
            price_csv.parent.mkdir(parents=True, exist_ok=True)
            combined.to_csv(price_csv)
            print(f"\n✅ Saved merged ENTSO-E data to {price_csv}")
            print(f"   Rows: {len(combined):,}")
            print(f"   Range: {combined.index[0]} → {combined.index[-1]}")
        else:
            print("⏭️  Skipping price download for this area (skip-price/weather-only).")

        # Weather: use Open-Meteo archive for the same period
        if not args.no_weather:
            lat_lon = default_lat_lon.get(area, (args.lat, args.lon))
            lat, lon = lat_lon if lat_lon else (args.lat, args.lon)
            weather_dir = Path(__file__).parents[1] / 'data' / 'weather'
            weather_dir.mkdir(parents=True, exist_ok=True)
            weather_csv = weather_dir / f"{area}_weather.csv"
            
            try:
                download_open_meteo(lat, lon, start_date.isoformat(), end_date.isoformat(), weather_csv)
            except Exception as e:
                print(f'Weather download failed: {e}')
                print('You can still run the pipeline using synthetic weather proxies.')

    print('\nDone.')


if __name__ == '__main__':
    main()
