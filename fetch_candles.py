#!/usr/bin/env python3
"""Fetch closed spot candles for later ChatGPT analysis; no trading or secrets."""
from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BYBIT = "https://api.bybit.com/v5/market/kline"
BINANCE = "https://data-api.binance.vision/api/v3/klines"
INTERVALS = {"15m": ("15", "15m", 15), "1h": ("60", "1h", 60), "4h": ("240", "4h", 240)}
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "PUMPUSDT,ALGOUSDT,NEARUSDT,ICPUSDT,BTCUSDT,SOLUSDT,TIAUSDT").split(",") if s.strip()]
COUNT = min(250, max(40, int(os.getenv("CANDLE_COUNT", "220"))))
OUTPUT = Path(os.getenv("OUTPUT", "data/latest.json"))
HTTP_TIMEOUT_SECONDS = max(2, min(15, int(os.getenv("HTTP_TIMEOUT_SECONDS", "5"))))
# Default to strict Bybit-only operation.  A fallback may be enabled manually
# for diagnostics, but it is always labelled and never represents Bybit data.
ALLOW_BINANCE_FALLBACK = os.getenv("ALLOW_BINANCE_FALLBACK", "0").lower() in {"1", "true", "yes"}


def http_json(url: str, query: dict[str, object]) -> object:
    req = Request(url + "?" + urlencode(query), headers={"User-Agent": "SpotCandleBridge/1.0", "Accept": "application/json"})
    last_error: Exception | None = None
    for retry in range(2):
        try:
            with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            if retry < 1:
                time.sleep(0.5)
    raise RuntimeError(f"HTTP request failed: {last_error}")


def closed_rows(rows: list[list[object]], period_mins: int, now_ms: int) -> list[list[object]]:
    """Keep only completed candles, sorted ascending, with original price precision."""
    seen: dict[int, list[object]] = {}
    for row in rows:
        start_ms = int(row[0])
        if start_ms + period_mins * 60_000 > now_ms - 5_000:
            continue
        # Timestamp, O,H,L,C,V; quote turnover is not added as fake volume
        seen[start_ms] = [start_ms, *[str(v) for v in row[1:6]]]
    return [seen[x] for x in sorted(seen)][-COUNT:]


def fetch_bybit(symbol: str, now_ms: int) -> dict:
    out: dict = {}
    for frame, (bybit_interval, _, period) in INTERVALS.items():
        payload = http_json(BYBIT, {"category": "spot", "symbol": symbol, "interval": bybit_interval, "limit": COUNT + 2})
        if not isinstance(payload, dict) or payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit {frame}: {str(payload)[:160]}")
        raw = payload.get("result", {}).get("list", [])
        if not isinstance(raw, list) or len(raw) < 30:
            raise RuntimeError(f"Bybit {frame}: insufficient candles")
        out[frame] = closed_rows(raw, period, now_ms)
    return out


def fetch_binance(symbol: str, now_ms: int) -> dict:
    out: dict = {}
    for frame, (_, binance_interval, period) in INTERVALS.items():
        payload = http_json(BINANCE, {"symbol": symbol, "interval": binance_interval, "limit": COUNT + 2})
        if not isinstance(payload, list) or len(payload) < 30:
            raise RuntimeError(f"Binance {frame}: insufficient candles")
        out[frame] = closed_rows(payload, period, now_ms)
    return out


def fetch_symbol(symbol: str, now_ms: int) -> dict:
    problems: list[str] = []
    sources = [("bybit_spot", fetch_bybit)]
    if ALLOW_BINANCE_FALLBACK:
        sources.append(("binance_spot_fallback_NOT_bybit", fetch_binance))
    for source, fetcher in sources:
        try:
            frames = fetcher(symbol, now_ms)
            if not all(len(frames[tf]) >= 30 for tf in INTERVALS):
                raise RuntimeError("Too few completed candles")
            latest = {tf: frames[tf][-1][0] + period * 60_000 for tf, (_, _, period) in INTERVALS.items()}
            freshness = {tf: now_ms - latest[tf] <= 2 * period * 60_000 for tf, (_, _, period) in INTERVALS.items()}
            return {"status": "ok" if all(freshness.values()) else "stale", "source": source, "closed_utc_ms": latest, "fresh": freshness, "frames": frames, "fallback_reasons": problems}
        except Exception as exc:
            problems.append(f"{source}: {str(exc)[:180]}")
    return {"status": "unavailable", "source": None, "reasons": problems, "frames": {}}


def main() -> int:
    now_ms = int(time.time() * 1000)
    result = {"schema_version": "1.0", "generated_at_utc": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat(),
              "generated_at_ms": now_ms, "market_type": "spot_only", "not_trading_advice": True,
              "columns": ["open_time_ms", "open", "high", "low", "close", "base_volume"], "symbols": {}}
    for symbol in dict.fromkeys(SYMBOLS):
        print(f"Fetching {symbol}...", file=sys.stderr)
        result["symbols"][symbol] = fetch_symbol(symbol, now_ms)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(OUTPUT)
    good = sum(x["status"] == "ok" for x in result["symbols"].values())
    print(f"Complete: {good}/{len(result['symbols'])} current symbols", file=sys.stderr)
    # Explicit nonzero if all data is absent, to avoid silently presenting a successful scan.
    return 0 if good else 2


if __name__ == "__main__":
    raise SystemExit(main())
