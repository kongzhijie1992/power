#!/usr/bin/env python3
"""Convert ENTSOe GUI CSV exports to the project's hourly day-ahead CSV.

Behavior:
- Reads the GUI CSV with 15-minute MTU ranges and both Sequence 1/2 rows.
- Filters to a chosen Sequence (default: 1), parses the MTU start timestamp
  (day-first format), converts the price column to numeric, resamples to
  hourly by mean, and writes a CSV with a datetime index and a `value` column.

Usage example:
  .venv\Scripts\python scripts\convert_entsoe.py \
    --input "data\DE\GUI_ENERGY_PRICES_202501010000-202601010000 (1).csv" \
    --output data\DE\day_ahead.csv --sequence 1 --resample H
"""
import argparse
from pathlib import Path
import pandas as pd


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="Path to GUI CSV export")
    p.add_argument("--output", required=True, help="Path to write processed CSV")
    p.add_argument(
        "--sequence",
        type=int,
        default=1,
        choices=[1, 2],
        help="Sequence to prefer (1 or 2)",
    )
    p.add_argument(
        "--both",
        action="store_true",
        help="Write both Sequence 1 and Sequence 2 outputs",
    )
    p.add_argument(
        "--resample", default="H", help="Pandas resample rule, e.g. H for hourly"
    )
    p.add_argument(
        "--tz", default="UTC", help="Timezone to localize timestamps to (e.g. UTC)"
    )
    args = p.parse_args()

    src = Path(args.input)
    dst = Path(args.output)
    if not src.exists():
        raise SystemExit(f"Input not found: {src}")

    # Read CSV (file typically contains quoted fields)
    df = pd.read_csv(src, dtype=str)

    # Column names observed in GUI exports
    mtu_col = next((c for c in df.columns if "MTU" in c or "MTU" in c), df.columns[0])
    price_col = next(
        (c for c in df.columns if "Day-ahead Price" in c or "Day-ahead" in c), None
    )
    seq_col = next((c for c in df.columns if "Sequence" in c), None)

    if price_col is None:
        raise SystemExit("Could not find a Day-ahead price column in CSV")

    # We'll optionally create one or two outputs depending on --both
    def process_for_sequence(seq_number):
        df_seq = df.copy()
        seq_text = f"Sequence {seq_number}"
        if seq_col is not None:
            df_seq = df_seq[df_seq[seq_col].str.contains(seq_text, na=False)]

        # Parse MTU start time (format: '31/12/2024 23:00:00 - 31/12/2024 23:15:00')
        df_seq["mtu_start"] = df_seq[mtu_col].str.split(" - ").str[0]
        df_seq["timestamp"] = pd.to_datetime(
            df_seq["mtu_start"], dayfirst=True, errors="coerce"
        )
        if df_seq["timestamp"].isna().any():
            bad = df_seq[df_seq["timestamp"].isna()].head(5)
            raise SystemExit(
                f"Failed to parse some MTU timestamps. Sample rows:\n{bad.to_csv(index=False)}"
            )

        # Convert price to numeric
        df_seq["price"] = pd.to_numeric(
            df_seq[price_col].str.replace(",", "."), errors="coerce"
        )
        if df_seq["price"].isna().all():
            raise SystemExit(
                "Parsed prices are all NaN. Check the input file's price format."
            )

        # Build a datetime-indexed series and resample
        df_seq = df_seq.set_index("timestamp")
        series = df_seq["price"].resample(args.resample).mean()

        # Localize timestamps to requested timezone (assume parsed times are UTC by label)
        try:
            series = series.tz_localize(args.tz)
        except Exception:
            # If already tz-aware or localization failed, try convert
            try:
                series = series.tz_convert(args.tz)
            except Exception:
                pass

        return series

    # per-sequence parsing and validation happens inside process_for_sequence()

    # Ensure output directory exists
    dst.parent.mkdir(parents=True, exist_ok=True)

    outputs = []
    if args.both:
        # derive base name from dst
        base = dst.with_suffix("")
        out1 = dst.parent / (base.name + "_seq1.csv")
        out2 = dst.parent / (base.name + "_seq2.csv")
        s1 = process_for_sequence(1)
        s2 = process_for_sequence(2)
        s1.rename("value").to_frame().to_csv(out1, index_label="datetime")
        s2.rename("value").to_frame().to_csv(out2, index_label="datetime")
        print(f"Wrote {len(s1)} rows to {out1}")
        print(f"Wrote {len(s2)} rows to {out2}")
        outputs = [out1, out2]
    else:
        s = process_for_sequence(args.sequence)
        out = dst
        s.rename("value").to_frame().to_csv(out, index_label="datetime")
        print(f"Wrote {len(s)} rows to {out}")
        outputs = [out]

    # return outputs for potential programmatic use
    return outputs


if __name__ == "__main__":
    main()
