#!/usr/bin/env python3
"""Generate sample ENTSO-E-formatted CSV files for 2023 and 2024."""
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np

# Create 2024 sample (365 days)
rows_2024 = [
    ['MTU (UTC)', 'Area', 'Sequence', 'Day-ahead Price (EUR/MWh)', 'Intraday Period (UTC)', 'Intraday Price (EUR/MWh)'],
]

base = datetime(2024, 1, 1, 0, 0)
np.random.seed(42)

for day in range(365):
    # Base price varies by day (winter higher, summer lower)
    day_price = 60 + 30 * np.sin(2 * np.pi * day / 365)
    
    for hour in range(24):
        # Hourly variation
        hour_price = day_price + 30 * np.sin(2 * np.pi * hour / 24)
        
        for quarter in range(4):
            ts = base + timedelta(days=day, hours=hour, minutes=quarter*15)
            ts_end = ts + timedelta(minutes=15)
            mtu = f'{ts.strftime("%d/%m/%Y %H:%M:%S")} - {ts_end.strftime("%d/%m/%Y %H:%M:%S")}'
            
            # Add realistic variation
            price = hour_price + np.random.normal(0, 2)
            
            rows_2024.append([mtu, 'BZN|DE-LU', 'Sequence Sequence 1', f'{price:.2f}', '', ''])

# Create 2023 sample (365 days)
rows_2023 = [
    ['MTU (UTC)', 'Area', 'Sequence', 'Day-ahead Price (EUR/MWh)', 'Intraday Period (UTC)', 'Intraday Price (EUR/MWh)'],
]

base = datetime(2023, 1, 1, 0, 0)

for day in range(365):
    day_price = 60 + 30 * np.sin(2 * np.pi * day / 365) + 10  # 2023 slightly higher
    
    for hour in range(24):
        hour_price = day_price + 30 * np.sin(2 * np.pi * hour / 24)
        
        for quarter in range(4):
            ts = base + timedelta(days=day, hours=hour, minutes=quarter*15)
            ts_end = ts + timedelta(minutes=15)
            mtu = f'{ts.strftime("%d/%m/%Y %H:%M:%S")} - {ts_end.strftime("%d/%m/%Y %H:%M:%S")}'
            
            price = hour_price + np.random.normal(0, 2.5)
            
            rows_2023.append([mtu, 'BZN|DE-LU', 'Sequence Sequence 1', f'{price:.2f}', '', ''])

# Write files
for rows, filename in [(rows_2024, 'GUI_2024_sample.csv'), (rows_2023, 'GUI_2023_sample.csv')]:
    with open(filename, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(','.join(f'"{c}"' for c in r) + '\n')
    print(f'Created {filename} with {len(rows)-1} data rows')
