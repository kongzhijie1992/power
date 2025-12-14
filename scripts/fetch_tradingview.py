#!/usr/bin/env python3
"""Fetch commodity proxies from TradingView and write data/market/commodities.csv.

Inputs (env):
  - TV_USERNAME / TV_PASSWORD, or TV_SESSIONID / TV_USERID for cookie login.

Symbols (edit as needed):
  - gas:  ICEEUR:TFM1!   (TTF front month, EUR/MWh)
  - co2:  ICEEUR:EUA1!   (EUA front, EUR/t)
  - coal: ICEEUR:API2!   (API2 front, EUR/ton; no FX conversion applied)

Output: data/market/commodities.csv with columns datetime, gas, coal, co2 (hourly, forward-filled).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
from tvDatafeed import Interval, TvDatafeed

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")
log = logging.getLogger("fetch_tradingview")

OUT_PATH = Path("data/market/commodities.csv")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Default symbols (can be tweaked per desk preference)
SYMBOLS = {
    "gas": ("TFM1!", "ICEEUR"),   # TTF front month, EUR/MWh
    "co2": ("EUA1!", "ICEEUR"),   # EUA front, EUR/t
    "coal": ("API2!", "ICEEUR"),  # API2 front, EUR/ton
}


def make_client() -> TvDatafeed:
    user = os.getenv("TV_USERNAME")
    pwd = os.getenv("TV_PASSWORD")
    sid = os.getenv("TV_SESSIONID")
    uid = os.getenv("TV_USERID")
    if sid and uid:
        return TvDatafeed(auto_login=False, token=sid, user=uid)
    return TvDatafeed(username=user, password=pwd, auto_login=True)


def fetch_series(tv: TvDatafeed, symbol: str, exchange: str) -> pd.Series:
    df = tv.get_hist(
        symbol=symbol,
        exchange=exchange,
        interval=Interval.in_daily,
        n_bars=900,  # ~3y
    )
    if df is None or df.empty:
        raise ValueError(f"No data for {exchange}:{symbol}")
    s = df["close"].copy()
    s.name = f"{exchange}:{symbol}"
    return s


def main():
    tv = make_client()
    rows = []
    for name, (symbol, exch) in SYMBOLS.items():
        try:
            s = fetch_series(tv, symbol, exch)
        except Exception as e:  # noqa: BLE001
            log.warning("Failed %s (%s:%s): %s", name, exch, symbol, e)
            continue
        s.name = name
        rows.append(s)

    if not rows:
        raise SystemExit("No series fetched; check credentials/symbols")

    df = pd.concat(rows, axis=1).sort_index().ffill()
    out = (
        df.resample("1H")
        .ffill()
        .reset_index()
        .rename(columns={"datetime": "datetime"})
    )
    out.to_csv(OUT_PATH, index=False)
    log.info("Saved %s (rows=%d)", OUT_PATH, len(out))


if __name__ == "__main__":
    main()
