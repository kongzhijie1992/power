#!/usr/bin/env python3
"""Diagnose ENTSO-E API issues.

Usage:
  python scripts/diagnose_entsoe.py
"""
import os
from pathlib import Path
import requests
import xml.etree.ElementTree as ET

# Load token from .env
env_path = Path(__file__).parents[1] / '.env'
token = None
if env_path.exists():
    for line in env_path.read_text().strip().split('\n'):
        if 'ENTSOE_API_TOKEN' in line and '=' in line:
            token = line.split('=', 1)[1].strip()
            break

if not token:
    raise SystemExit('ENTSOE_API_TOKEN not found in .env')

print(f"Token (masked): {token[:20]}...{token[-10:]}")

# Test 1: Simple API health check
print("\n=== Test 1: API Health Check ===")
url = "https://web-api.tp.entsoe.eu/api"
params = {
    'securityToken': token,
    'documentType': 'A44',  # Day-ahead prices
    'in_Domain': '10Y1001A1001A82H',  # DE/LU
    'out_Domain': '10Y1001A1001A82H',
    'periodStart': '202512050000Z',  # older date, might fail if data unavailable
    'periodEnd': '202512050100Z',    # 1 hour period
}

print(f"GET {url}")
print(f"Params: {params}")
r = requests.get(url, params=params, timeout=10)
print(f"Status: {r.status_code}")
print(f"Headers: {dict(r.headers)}")
print(f"Response (first 500 chars):\n{r.text[:500]}")

if r.status_code == 400:
    print("\n=== Analyzing 400 Error ===")
    try:
        root = ET.fromstring(r.content)
        # Print all text elements
        for elem in root.iter():
            if elem.text and elem.text.strip():
                print(f"{elem.tag}: {elem.text.strip()}")
    except ET.ParseError as e:
        print(f"Failed to parse response: {e}")

# Test 2: Try with a very recent date (last 24 hours)
print("\n=== Test 2: Recent Data (Last 24 Hours) ===")
import datetime as dt
now = dt.datetime.utcnow()
start = (now - dt.timedelta(days=1)).strftime('%Y%m%d%H%MZ')
end = now.strftime('%Y%m%d%H%MZ')

params2 = {
    'securityToken': token,
    'documentType': 'A44',
    'in_Domain': '10Y1001A1001A82H',
    'out_Domain': '10Y1001A1001A82H',
    'periodStart': start,
    'periodEnd': end,
}

print(f"periodStart: {start}, periodEnd: {end}")
r2 = requests.get(url, params=params2, timeout=10)
print(f"Status: {r2.status_code}")
if r2.status_code != 200:
    print(f"Response (first 300 chars):\n{r2.text[:300]}")

# Test 3: Try different document types
print("\n=== Test 3: Different Document Types ===")
doc_types = [
    ('A44', 'Day-ahead Prices'),
    ('A45', 'Year-ahead Prices'),
    ('A81', 'Day-ahead Aggregated Load'),
]

for doctype, desc in doc_types:
    params3 = {
        'securityToken': token,
        'documentType': doctype,
        'in_Domain': '10Y1001A1001A82H',
        'out_Domain': '10Y1001A1001A82H',
        'periodStart': start,
        'periodEnd': end,
    }
    r3 = requests.get(url, params=params3, timeout=10)
    print(f"{doctype} ({desc}): {r3.status_code}")

# Test 4: Validate token directly (if possible)
print("\n=== Test 4: Token Validation ===")
# ENTSO-E might have a health endpoint
health_url = "https://web-api.tp.entsoe.eu/api"
health_params = {
    'securityToken': token,
    'documentType': 'A44',
    'in_Domain': '10Y1001A1001A82H',
    'out_Domain': '10Y1001A1001A82H',
    'periodStart': now.strftime('%Y%m%d0000Z'),
    'periodEnd': now.strftime('%Y%m%d2300Z'),
}
r4 = requests.get(health_url, params=health_params, timeout=10)
print(f"Status: {r4.status_code}")
if r4.status_code == 200:
    print("✓ Token appears valid and data available")
    # Count price points
    try:
        root = ET.fromstring(r4.content)
        points = root.findall('.//{urn:iec62325.351:tc57wg16:451-1:publicationdocument:7:3}Point')
        print(f"Data points received: {len(points)}")
    except Exception as e:
        print(f"Could not parse response: {e}")
elif r4.status_code == 401:
    print("✗ Token appears invalid or expired")
elif r4.status_code == 400:
    print("✗ Bad request parameters")
else:
    print(f"✗ Unexpected status code")

print("\n=== Diagnosis Complete ===")
