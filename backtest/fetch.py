"""Download closed spot OHLCV history: Binance public data API, Bybit spot as fallback."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

BINANCE = "https://data-api.binance.vision/api/v3/klines"
BYBIT_HOSTS = ("https://api.bybit.com", "https://api.bytick.com")
MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}
BYBIT_IV = {"15m": "15", "1h": "60", "4h": "240", "1d": "D"}
COLS = ["time", "open", "high", "low", "close", "volume"]


def _get(url: str, query: dict) -> object:
    req = Request(url + "?" + urlencode(query), headers={"User-Agent": "LattiaKattoBacktest/1.0"})
    err: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as exc:  # network hiccup or HTTP error
            err = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{url}: {err}")


def binance(symbol: str, tf: str, start_ms: int, end_ms: int) -> list[list]:
    rows, cur = [], start_ms
    while cur < end_ms:
        page = _get(BINANCE, {"symbol": symbol, "interval": tf, "startTime": cur, "endTime": end_ms, "limit": 1000})
        if not isinstance(page, list) or not page:
            break
        rows += [[int(x[0]), *map(float, x[1:6])] for x in page]
        cur = int(page[-1][0]) + MINUTES[tf] * 60_000
        time.sleep(0.05)
    return rows


def bybit(symbol: str, tf: str, start_ms: int, end_ms: int) -> list[list]:
    for host in BYBIT_HOSTS:
        try:
            rows, end = [], end_ms
            while end > start_ms:
                page = _get(host + "/v5/market/kline", {"category": "spot", "symbol": symbol, "interval": BYBIT_IV[tf],
                                                        "start": start_ms, "end": end, "limit": 1000})
                lst = page.get("result", {}).get("list", []) if isinstance(page, dict) and page.get("retCode") == 0 else []
                if not lst:
                    break
                rows += [[int(x[0]), *map(float, x[1:6])] for x in lst]
                end = min(int(x[0]) for x in lst) - 1
                time.sleep(0.05)
            if rows:
                return rows
        except RuntimeError:
            continue
    return []


def load(symbol: str, tf: str, start: str, end: str, cache: Path) -> tuple[pd.DataFrame, str]:
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{symbol}_{tf}_{start}_{end}.csv"
    if f.exists():
        return pd.read_csv(f), source_of(symbol, tf, start, end, cache)
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    now_ms = int(time.time() * 1000)
    source = "binance"
    try:
        rows = binance(symbol, tf, start_ms, end_ms)
    except RuntimeError:
        rows = []
    if len(rows) < 300:
        source, rows = "bybit", bybit(symbol, tf, start_ms, end_ms)
    if not rows:
        return pd.DataFrame(columns=COLS), "missing"
    df = pd.DataFrame(rows, columns=COLS).drop_duplicates("time").sort_values("time")
    df = df[df["time"] + MINUTES[tf] * 60_000 <= min(end_ms, now_ms)].reset_index(drop=True)  # closed bars only
    df.to_csv(f, index=False)
    (cache / f"{f.stem}.source").write_text(source)
    return df, source


def source_of(symbol: str, tf: str, start: str, end: str, cache: Path) -> str:
    s = cache / f"{symbol}_{tf}_{start}_{end}.source"
    return s.read_text() if s.exists() else "unknown"
