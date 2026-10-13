#!/usr/bin/env python3
"""Read-only Bybit perpetual OHLCV snapshot for ChatGPT. No credentials or trading."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASES = ("https://api.bybit.com", "https://api.bytick.com")
SYMBOL = "PUMPFUNUSDT"
CATEGORY = "linear"
FRAMES = {"1m": (1, 120), "15m": (15, 180), "1h": (60, 120), "4h": (240, 90)}
DEST = Path("data/perp/latest.json")
REPORT = Path("data/perp/latest.md")


def utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def fetch(path: str, params: dict) -> dict:
    errors = []
    for base in BASES:
        url = base + path + "?" + urlencode(params)
        try:
            req = Request(url, headers={"Accept": "application/json", "User-Agent": "PUMP-Perp-Candle-Reader/1.0"})
            with urlopen(req, timeout=15) as reply:
                payload = json.load(reply)
            if not isinstance(payload, dict) or payload.get("retCode") != 0:
                raise RuntimeError("Bybit retCode=" + str(payload.get("retCode") if isinstance(payload, dict) else "invalid"))
            return payload
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            errors.append(base + ": " + str(exc)[:140])
    raise RuntimeError(" / ".join(errors))


def rows_for(frame: str, period: int, limit: int, now_ms: int) -> list[list]:
    payload = fetch("/v5/market/kline", {
        "category": CATEGORY, "symbol": SYMBOL, "interval": str(period), "limit": limit + 3
    })
    if payload.get("result", {}).get("symbol") != SYMBOL:
        raise ValueError("Unexpected market symbol")
    dedup = {}
    for raw in payload["result"]["list"]:
        stamp = int(raw[0])
        # Open candles cannot be used to confirm SL/TP hits.
        if stamp + period * 60000 > now_ms - 3000:
            continue
        prices = [float(p) for p in raw[1:5]]
        op, hi, lo, cl = prices
        volume = float(raw[5])
        if not (0 < lo <= min(op, cl) <= max(op, cl) <= hi and volume >= 0):
            raise ValueError("Invalid OHLCV data")
        dedup[stamp] = [stamp, *[str(v) for v in raw[1:6]]]
    ordered = [dedup[t] for t in sorted(dedup)][-limit:]
    if len(ordered) < 20:
        raise ValueError("Insufficient closed bars for " + frame)
    step = period * 60000
    if any(ordered[i][0] - ordered[i - 1][0] != step for i in range(1, len(ordered))):
        raise ValueError("Gaps in " + frame)
    if now_ms - (ordered[-1][0] + step) > (2 * step + 120000):
        raise ValueError("Stale " + frame + " candles")
    return ordered


WORKER_URL = "https://spot-candle-bridge.zurab-gudushauri1994.workers.dev/perp"


def fetch_worker(now_ms: int) -> dict:
    """Prefer the existing Frankfurt-hosted, read-only Bybit proxy."""
    req = Request(WORKER_URL, headers={"Accept": "application/json", "User-Agent": "PUMP-Perp-Candle-Reader/1.0"})
    with urlopen(req, timeout=45) as reply:
        payload = json.load(reply)
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError("Worker did not return verified perpetual candles")
    if payload.get("source") != "bybit_v5_linear_perpetual" or payload.get("market_type") != "linear_perpetual":
        raise ValueError("Worker source mismatch; spot substitution prohibited")
    if payload.get("symbol") != SYMBOL or payload.get("category") != CATEGORY:
        raise ValueError("Worker market mismatch")
    ts = int(payload.get("generated_at_ms", 0))
    if abs(now_ms - ts) > 120_000:
        raise ValueError("Worker snapshot older than two minutes")
    raw_frames = payload.get("timeframes", {})
    verified_frames = {}
    for name, (period, limit) in FRAMES.items():
        raw = raw_frames.get(name)
        if not isinstance(raw, list) or len(raw) < 20:
            raise ValueError("Worker missing candle history for " + name)
        prev = None
        rows = []
        for row in raw:
            start = int(row[0])
            if prev is not None and start - prev != period * 60_000:
                raise ValueError("Worker data gap for " + name)
            prev = start
            if start + period * 60_000 > ts - 3000:
                raise ValueError("Worker included unfinished candle")
            op, hi, lo, cl, vol = [float(x) for x in row[1:6]]
            if not (lo > 0 and lo <= min(op, cl) and max(op, cl) <= hi and vol >= 0):
                raise ValueError("Invalid Worker OHLCV")
            rows.append([start, *[str(x) for x in row[1:6]]])
        if now_ms - (rows[-1][0] + period * 60_000) > (period * 120_000 + 120_000):
            raise ValueError("Stale Worker timeframe " + name)
        verified_frames[name] = rows[-limit:]
    return {
        "status": "ok", "source": "bybit_v5_linear_perpetual_via_cloudflare_worker",
        "symbol": SYMBOL, "category": CATEGORY,
        "generated_at_ms": ts, "generated_at_utc": utc(ts),
        "columns": ["open_time_ms", "open", "high", "low", "close", "base_volume"],
        "timeframes": verified_frames,
        "last_closed_utc": {name: utc(frames[-1][0] + FRAMES[name][0] * 60000)
                            for name, frames in verified_frames.items()},
        "note": "Closed Bybit linear perpetual trade-price OHLCV. Intrabar event ordering and mark-price triggers unverified."
    }


def build() -> dict:
    now_ms = int(time.time() * 1000)
    try:
        return fetch_worker(now_ms)
    except Exception as exc:
        print("Cloudflare Bybit perpetual bridge unavailable; trying direct Bybit:", str(exc)[:220])
    instrument = fetch("/v5/market/instruments-info", {"category": CATEGORY, "symbol": SYMBOL})
    found = [x for x in instrument.get("result", {}).get("list", []) if x.get("symbol") == SYMBOL]
    if not found or found[0].get("status") != "Trading":
        raise RuntimeError("Bybit did not confirm an active PUMPFUNUSDT linear instrument")
    frames = {name: rows_for(name, period, lim, now_ms) for name, (period, lim) in FRAMES.items()}
    return {
        "status": "ok", "source": "bybit_v5_linear_perpetual", "symbol": SYMBOL,
        "category": CATEGORY, "generated_at_ms": now_ms, "generated_at_utc": utc(now_ms),
        "columns": ["open_time_ms", "open", "high", "low", "close", "base_volume"],
        "timeframes": frames,
        "last_closed_utc": {k: utc(v[-1][0] + FRAMES[k][0] * 60000) for k, v in frames.items()},
        "note": "Only complete exchange-traded candles. OHLC alone cannot order two hits inside one bar; mark-price triggers may differ."
    }


def main():
    try:
        out = build()
    except Exception as exc:
        # Never overwrite the last good candle snapshot with fabricated bars.
        print("Bybit perpetual OHLC fetch failed: " + str(exc))
        raise SystemExit(1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# PUMPFUNUSDT – Bybit Linear Perpetual OHLCV", "",
        "Source: Bybit v5 /market/kline; category=linear; symbol=PUMPFUNUSDT",
        "Snapshot UTC: " + out["generated_at_utc"], "",
        "| Frame | Closed UTC | O | H | L | C | Volume |",
        "|---|---|---:|---:|---:|---:|---:|"
    ]
    for name in FRAMES:
        bar = out["timeframes"][name][-1]
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(name, utc(bar[0] + FRAMES[name][0] * 60000), *bar[1:]))
    lines += ["", "Full closed 1m / 15m / 1h / 4h OHLCV history: data/perp/latest.json.",
              "Always check freshness. 1-minute high/low can test approximate TP/SL hits, but exact tick order and trigger-price type remain unknown.", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
