#!/usr/bin/env python3
"""Fetch real ENTSO-E day-ahead prices using the API token.

Usage:
  python scripts/fetch_entsoe_data.py --area DE --days 90

Requires ENTSOE_API_TOKEN environment variable or .env file.

Creates:
 - data/<AREA>/day_ahead_real.csv (hourly prices from ENTSO-E API, column 'value')
 - data/weather/<area>_weather.csv (hourly weather from Open-Meteo, no key required)
"""
import argparse
import os
from pathlib import Path
import datetime as dt

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


def fetch_entsoe_prices(api_token, area_code, start_date, end_date, out_csv_path):
    """Fetch day-ahead prices from ENTSO-E API.
    
    Args:
        api_token: ENTSO-E API token
        area_code: ISO code (e.g., 'DE_LU' for Germany/Luxembourg)
        start_date: ISO date string (YYYY-MM-DD)
        end_date: ISO date string (YYYY-MM-DD)
        out_csv_path: path to write CSV with 'value' column
    """
    # ENTSO-E area code mappings (EIC codes)
    area_map = {
        'DE_LU': '10Y1001A1001A82H',  # Germany/Luxembourg
        'FR': '10YFR-RTE------C',      # France
        'IT': '10Y1001A1001A73V',      # Italy
        'ES': '10YES-REE------0',      # Spain
        'NL': '10YNL----------L',      # Netherlands
        'BE': '10YBE----------2',      # Belgium
    }
    
    eic_code = area_map.get(area_code, area_code)  # use provided code as fallback
    
    # ENTSO-E API endpoint for day-ahead market prices
    url = "https://web-api.tp.entsoe.eu/api"
    
    # Convert dates to ENTSO-E format (YYYYMMDDTHHMM)
    start_ts = f"{start_date.replace('-', '')}T0000Z"
    end_ts = f"{end_date.replace('-', '')}T2300Z"
    
    params = {
        'securityToken': api_token,
        'documentType': 'A44',  # Day-ahead prices
        'in_Domain': eic_code,
        'out_Domain': eic_code,
        'periodStart': start_ts,
        'periodEnd': end_ts,
    }
    
    print(f"Fetching ENTSO-E data for {area_code} ({eic_code}) from {start_date} to {end_date}...")
    print(f"Requesting: {url} with params {params}")
    
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error {r.status_code}: {r.text[:200]}")
        raise SystemExit(f"ENTSO-E API request failed: {e}")
    except requests.exceptions.RequestException as e:
        raise SystemExit(f"ENTSO-E API request failed: {e}")
    
    # Parse XML response (ENTSO-E uses XML)
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(r.content)
        # Extract price points from XML
        # Namespace handling required
        ns = {'': 'urn:iec62325.351:tc57wg16:451-1:publicationdocument:7:3'}
        timeseries = root.findall('.//{urn:iec62325.351:tc57wg16:451-1:publicationdocument:7:3}TimeSeries')
        
        if not timeseries:
            # Try without namespace
            timeseries = root.findall('.//TimeSeries')
        
        prices = []
        timestamps = []
        
        for ts in timeseries:
            period = ts.find('.//{urn:iec62325.351:tc57wg16:451-1:publicationdocument:7:3}Period')
            if period is None:
                period = ts.find('.//Period')
            
            if period is not None:
                time_interval = period.find('.//{urn:iec62325.351:tc57wg16:451-1:publicationdocument:7:3}timeInterval')
                if time_interval is None:
                    time_interval = period.find('.//timeInterval')
                
                start_elem = time_interval.find('.//{urn:iec62325.351:tc57wg16:451-1:publicationdocument:7:3}start') if time_interval is not None else None
                if start_elem is None and time_interval is not None:
                    start_elem = time_interval.find('.//start')
                
                if start_elem is not None:
                    start_time = pd.to_datetime(start_elem.text)
                    
                    points = period.findall('.//{urn:iec62325.351:tc57wg16:451-1:publicationdocument:7:3}Point')
                    if not points:
                        points = period.findall('.//Point')
                    
                    for i, point in enumerate(points):
                        price_elem = point.find('.//{urn:iec62325.351:tc57wg16:451-1:publicationdocument:7:3}price.amount')
                        if price_elem is None:
                            price_elem = point.find('.//price.amount')
                        
                        if price_elem is not None:
                            price = float(price_elem.text)
                            ts = start_time + dt.timedelta(hours=i)
                            timestamps.append(ts)
                            prices.append(price)
        
        if not prices:
            raise SystemExit("No price data found in ENTSO-E response. Check area code and date range.")
        
        # Create DataFrame and save
        df = pd.DataFrame({'value': prices}, index=timestamps)
        df.index.name = 'datetime'
        
        out_path = Path(out_csv_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path)
        
        print(f"Saved {len(df)} hours of real ENTSO-E prices to {out_path}")
        return out_path
        
    except ET.ParseError as e:
        print(f"Failed to parse ENTSO-E response: {e}")
        print(f"Response: {r.text[:500]}")
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
    p.add_argument('--lat', type=float, default=52.52, help='Latitude for weather data (Germany)')
    p.add_argument('--lon', type=float, default=13.405, help='Longitude for weather data (Germany)')
    p.add_argument('--days', type=int, default=90, help='Number of days to fetch (historical)')
    args = p.parse_args()

    api_token = os.getenv('ENTSOE_API_TOKEN')
    if not api_token:
        raise SystemExit(
            'ENTSOE_API_TOKEN not set. Please:\n'
            '  1. Set environment variable: export ENTSOE_API_TOKEN=<your-token>\n'
            '  2. Or add to .env file: ENTSOE_API_TOKEN=<your-token>'
        )

    area = args.area
    days = args.days

    # Prices: fetch real ENTSO-E data
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    start_str = start.isoformat()
    end_str = (end - dt.timedelta(days=1)).isoformat()

    data_dir = Path(__file__).parents[1] / 'data' / area
    data_dir.mkdir(parents=True, exist_ok=True)
    price_csv = data_dir / 'day_ahead_real.csv'
    
    try:
        fetch_entsoe_prices(api_token, area, start_str, end_str, price_csv)
    except Exception as e:
        print(f'ENTSO-E fetch failed: {e}')
        raise

    # Weather: use Open-Meteo archive for the same period
    weather_dir = Path(__file__).parents[1] / 'data' / 'weather'
    weather_dir.mkdir(parents=True, exist_ok=True)
    weather_csv = weather_dir / f"{area}_weather.csv"
    
    try:
        download_open_meteo(args.lat, args.lon, start_str, end_str, weather_csv)
    except Exception as e:
        print(f'Weather download failed: {e}')
        print('You can still run the pipeline using synthetic weather proxies.')

    print('\nDone.')


if __name__ == '__main__':
    main()
