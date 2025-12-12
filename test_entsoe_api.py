#!/usr/bin/env python3
"""
Simple ENTSOE API diagnostic test

This script makes a basic API request and prints the full response
to help diagnose what's wrong.
"""
import requests
from pathlib import Path
from datetime import datetime

# Load token
env_path = Path('.env')
if not env_path.exists():
    print("❌ .env file not found")
    exit(1)

token = None
with open(env_path) as f:
    for line in f:
        if line.startswith('ENTSOE_API_TOKEN='):
            token = line.split('=')[1].strip().strip('"\'')
            break

if not token:
    print("❌ Token not found in .env")
    exit(1)

print(f"Token: {token[:20]}...\n")

# Test parameters
base_url = "https://web-api.tp.entsoe.eu/api"
start_date = datetime(2024, 1, 1)
end_date = datetime(2024, 1, 3)  # 2 days to ensure data exists

# Try different combinations
tests = [
    {
        'name': 'Recommended (EIC 82H, YYYYMMDDHHMM, end=next-day 0000)',
        'params': {
            'securityToken': token,
            'documentType': 'A44',
            'In_Domain': '10Y1001A1001A82H',
            'Out_Domain': '10Y1001A1001A82H',
            'periodStart': start_date.strftime("%Y%m%d0000"),
            'periodEnd': (end_date).strftime("%Y%m%d0000"),
        }
    },
    {
        'name': 'Same but with Z suffix',
        'params': {
            'securityToken': token,
            'documentType': 'A44',
            'In_Domain': '10Y1001A1001A82H',
            'Out_Domain': '10Y1001A1001A82H',
            'periodStart': start_date.strftime("%Y%m%d0000") + 'Z',
            'periodEnd': (end_date).strftime("%Y%m%d0000") + 'Z',
        }
    },
    {
        'name': 'Alt code 82F',
        'params': {
            'securityToken': token,
            'documentType': 'A44',
            'In_Domain': '10Y1001A1001A82F',
            'Out_Domain': '10Y1001A1001A82F',
            'periodStart': start_date.strftime("%Y%m%d0000"),
            'periodEnd': (end_date).strftime("%Y%m%d0000"),
        }
    },
]

for test in tests:
    print(f"\n{'='*70}")
    print(f"Test: {test['name']}")
    print(f"{'='*70}")
    
    print("\nRequest URL:", base_url)
    print("\nParameters:")
    for key, val in test['params'].items():
        if key == 'securityToken':
            print(f"  {key}: {val[:20]}...")
        else:
            print(f"  {key}: {val}")
    
    try:
        response = requests.get(base_url, params=test['params'], timeout=15)
        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print(f"\nResponse Body (first 500 chars of {len(response.text)}):")
        print("-" * 70)
        print(response.text[:500])
        print("-" * 70)
        
        if response.status_code == 200:
            print("\n✅ SUCCESS! This parameter combination works.")
            break
        
    except Exception as e:
        print(f"\n❌ Request failed: {e}")

print("\n" + "="*70)
print("Diagnostic complete. Check output above for the actual error message.")
print("="*70)
