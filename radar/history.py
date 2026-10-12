"""Paged historical Bybit Spot download through the Frankfurt Worker only."""
from __future__ import annotations
import json, subprocess, time
from datetime import datetime, timezone

BRIDGE="https://spot-candle-bridge.zurab-gudushauri1994.workers.dev/history"

def download(symbol: str, days: int=90, interval: str="15", bridge: str=BRIDGE) -> list[list[object]]:
    minutes={"15":15,"60":60,"240":240}[interval]
    step=minutes*60_000; end=int(time.time()*1000)//step*step; start=end-days*86_400_000
    rows={}
    # One page has at most 1,000 rows. Pages overlap by one step and are deduplicated by time.
    cursor=start
    while cursor < end:
        page_end=min(end, cursor+999*step)
        url=f"{bridge}?symbol={symbol}&interval={interval}&start={cursor}&end={page_end}"
        p=subprocess.run(["curl","--silent","--show-error","--fail-with-body","--max-time","90",url],capture_output=True,text=True,check=True)
        data=json.loads(p.stdout)
        if data.get("source") != "bybit_spot" or data.get("market_type") != "spot_only": raise RuntimeError(f"invalid historical source for {symbol}: {data.get('reason')}")
        for r in data.get("rows",[]): rows[int(r[0])]=r
        cursor=page_end+step
    result=[rows[t] for t in sorted(rows)]
    if len(result)<max(60,int(days*86_400_000/step*.85)): raise RuntimeError(f"{symbol}: only {len(result)} historical candles")
    return result

def provenance(symbol: str, rows: list[list[object]]) -> dict:
    return {"symbol":symbol,"source":"bybit_spot","rows":len(rows),"first_closed_utc":datetime.fromtimestamp((int(rows[0][0])+900_000)/1000,tz=timezone.utc).isoformat(),"last_open_utc":datetime.fromtimestamp(int(rows[-1][0])/1000,tz=timezone.utc).isoformat()}
