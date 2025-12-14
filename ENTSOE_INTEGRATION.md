# ENTSO-E API Integration Status

## Current Status

- ✅ API fetch is working with chunked requests and merge-safe writes.
- ✅ Token is loaded from `.env` (`ENTSOE_API_TOKEN`), never committed.
- ✅ Multi-area pulls (30+ zones) already populated `data/<AREA>/day_ahead_real.csv` and matching weather.
- ⚙️ GUI converter/merger remain as fallbacks.

## What Works Today

- **Chunked fetch (recommended path):**
  ```bash
  python scripts/fetch_entsoe_data.py ^
    --areas DE_LU FR IT ES NL BE ^
    --start-date 2023-01-01 --end-date 2025-12-31 ^
    --chunk-days 60 --merge-existing
  ```
  - Writes price CSV per area (`day_ahead_real.csv`)
  - Auto-downloads Open-Meteo weather per area
  - Dedupes timestamps and merges existing data

- **GUI pipeline (fallback):**
  - `scripts/convert_entsoe.py` — convert GUI exports to hourly
  - `scripts/merge_years.py` — merge multiple GUI CSVs
  - `scripts/plot_sequences.py` — compare sequences

## Guidance and Troubleshooting

1. **Token check**
   - Ensure `.env` contains `ENTSOE_API_TOKEN=<your-token>`.
   - If you see HTTP 401, re-issue the token in the ENTSO-E portal.

2. **Avoid 400 errors on long ranges**
   - Always use `--chunk-days` (60–90) and let the script loop over chunks.
   - Keep `periodStart`/`periodEnd` within the same call under ~3 months.

3. **Merging without overwriting**
   - Use `--merge-existing` to append while deduping timestamps.
   - Outputs stay in `data/<AREA>/day_ahead_real.csv`; primary pipeline file is `data/<AREA>/day_ahead.csv`.

4. **Weather only**
   - `python scripts/fetch_entsoe_data.py --weather-only --area DE_LU --start-date 2023-01-01 --end-date 2025-12-31`

5. **Diagnostics**
   - `python scripts/diagnose_entsoe.py` to inspect responses and params.

## File Map

| File | Purpose |
|------|---------|
| `scripts/fetch_entsoe_data.py` | Chunked ENTSO-E API + weather, merge-safe |
| `scripts/diagnose_entsoe.py` | Inspect token/status and sample calls |
| `scripts/convert_entsoe.py` | GUI CSV → hourly converter |
| `scripts/merge_years.py` | Merge multiple GUI exports |
| `.env` | Holds `ENTSOE_API_TOKEN` (ignored by git) |

## Next Actions

- Use the API path for all updates; reserve GUI for rare fallbacks.
- Schedule periodic runs with `--merge-existing` to keep data fresh.
- If adding new areas, pass them via `--areas` and rerun the fetch command.

For ENTSO-E API reference, see https://web-api.tp.entsoe.eu/api.
