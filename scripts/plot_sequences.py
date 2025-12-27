import argparse
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt


def load_series(path: Path):
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.shape[1] == 1:
        return df.iloc[:, 0]
    # if multiple columns, try to find 'value'
    if "value" in df.columns:
        return df["value"]
    # fallback to first column
    return df.iloc[:, 0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seq1", default="data/DE/day_ahead_seq1.csv")
    p.add_argument("--seq2", default="data/DE/day_ahead_seq2.csv")
    p.add_argument("--out", default="data/DE/seq_compare.png")
    p.add_argument("--start", help="ISO date start (inclusive)")
    p.add_argument("--end", help="ISO date end (inclusive)")
    args = p.parse_args()

    p1 = Path(args.seq1)
    p2 = Path(args.seq2)
    if not p1.exists() or not p2.exists():
        raise SystemExit("Required sequence CSVs not found in data/DE/")

    s1 = load_series(p1)
    s2 = load_series(p2)

    # align
    s1, s2 = s1.align(s2, join="inner")

    if args.start:
        s1 = s1[s1.index >= pd.to_datetime(args.start)]
        s2 = s2[s2.index >= pd.to_datetime(args.start)]
    if args.end:
        s1 = s1[s1.index <= pd.to_datetime(args.end)]
        s2 = s2[s2.index <= pd.to_datetime(args.end)]

    # quick stats
    stats = pd.DataFrame({"seq1": s1.describe(), "seq2": s2.describe()})
    print(stats)

    # plot
    plt.figure(figsize=(12, 5))
    s1.plot(label="Sequence 1 (SDAC)", alpha=0.9)
    s2.plot(label="Sequence 2 (EXAA)", alpha=0.7)
    plt.legend()
    plt.title("DE Day-ahead: Sequence 1 vs Sequence 2")
    plt.ylabel("EUR/MWh")
    plt.tight_layout()
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(outp)
    print(f"Wrote plot to {outp}")


if __name__ == "__main__":
    main()
