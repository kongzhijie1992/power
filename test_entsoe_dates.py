#!/usr/bin/env python3
"""Test ENTSOE API with historical dates that should have data"""
import requests
from pathlib import Path
from datetime import datetime, timedelta

# Load token
env_path = Path(".env")
token = None
with open(env_path) as f:
    for line in f:
        if line.startswith("ENTSOE_API_TOKEN="):
            token = line.split("=")[1].strip().strip("\"'")
            break

if not token:
    print("❌ Token not found in .env")
    exit(1)

base_url = "https://web-api.tp.entsoe.eu/api"

# Test with dates that DEFINITELY have published data
tests = [
    ("2023-06-01", "2023-06-02", "Mid-2023 (should have data)"),
    ("2023-01-01", "2023-01-02", "Start of 2023"),
    ("2023-12-31", "2024-01-01", "Year transition"),
    ("2024-01-01", "2024-01-02", "Start of 2024"),
]

for start, end, desc in tests:
    start_date = datetime.strptime(start, "%Y-%m-%d")
    end_date = datetime.strptime(end, "%Y-%m-%d") + timedelta(
        days=1
    )  # inclusive end → next day 0000

    params = {
        "securityToken": token,
        "documentType": "A44",
        "In_Domain": "10Y1001A1001A82H",
        "Out_Domain": "10Y1001A1001A82H",
        "periodStart": start_date.strftime("%Y%m%d0000"),
        "periodEnd": end_date.strftime("%Y%m%d0000"),
    }

    response = requests.get(base_url, params=params, timeout=15)

    # Extract error message if present
    if "No matching data found" in response.text:
        print(f"❌ {desc} ({start} to {end.strftime('%Y-%m-%d')}): No data")
    elif response.status_code == 200:
        # Check if we got actual price data
        if "<Price>" in response.text or "<price.amount>" in response.text:
            print(f"✅ {desc} ({start} to {end.strftime('%Y-%m-%d')}): Data found!")
            print(f"   Response size: {len(response.text)} chars")
        else:
            print(
                f"⚠️  {desc} ({start} to {end.strftime('%Y-%m-%d')}): Status 200 but no <Price> tags"
            )
    else:
        print(
            f"❌ {desc} ({start} to {end.strftime('%Y-%m-%d')}): Status {response.status_code}"
        )

print("\n" + "=" * 70)
print("If all show 'No data' → Need to investigate data availability")
print("If any show 'Data found' → We can fetch that date range")
print("=" * 70)
