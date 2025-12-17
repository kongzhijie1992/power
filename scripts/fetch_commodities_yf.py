#!/usr/bin/env python3
"""Fetch free commodity proxies from Yahoo Finance and build data/market/commodities.csv.

Proxies (daily):
  - Gas: TTF=F (ICE TTF front-month, EUR/MWh)
  - Coal: MTF=F (ICE Rotterdam coal, USD/ton) -> converted to EUR/MWh with FX and 6.7 MWh/ton
  - CO2: KRBN (global carbon ETF, USD) -> used as a proxy; scaled to EUR by FX (units imperfect)
  - FX: EURUSD=X

Output columns: datetime, gas, coal, co2 (hourly, forward-filled).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")
log = logging.getLogger("fetch_commodities_yf")

OUT_PATH = Path("data/market/commodities.csv")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def download(ticker: str) -> pd.Series:
    df = yf.download(ticker, period="2y", interval="1d", progress=False)
    if df.empty or "Close" not in df.columns:
        raise ValueError(f"No data for {ticker}")
    s = df["Close"].copy()
    s.name = ticker
    return s


def main():
    gas = download("TTF=F")  # EUR/MWh
    coal_usd = download("MTF=F")  # USD/ton (proxy)
    co2_usd = download("KRBN")  # USD (ETF proxy)
    fx = download("EURUSD=X")  # USD per EUR

    df = pd.concat([gas, coal_usd, co2_usd, fx], axis=1).ffill()
    df["coal"] = (df["MTF=F"] / df["EURUSD=X"]) / 6.7  # EUR/MWh proxy
    df["co2"] = (df["KRBN"] / df["EURUSD=X"]).rename("co2")  # EUR proxy

    out = (
        pd.DataFrame(
            {
                "datetime": df.index,
                "gas": df["TTF=F"],
                "coal": df["coal"],
                "co2": df["co2"],
            }
        )
        .set_index("datetime")
        .resample("h")
        .ffill()
        .reset_index()
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)
    log.info("Saved commodities -> %s (rows=%d)", OUT_PATH, len(out))


if __name__ == "__main__":
    main()
