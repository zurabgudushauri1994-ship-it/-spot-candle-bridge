"""Walk-forward OHLCV backtest for early-momentum rules. No exchange keys or orders."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from .engine import frame, early_momentum


def test_pair(rows: list[list[object]], minutes: int = 15, fee_bps: float = 12.0, slippage_bps: float = 5.0, split: float = .70) -> dict:
    d = frame(rows, minutes)
    # First portion is development-only. The out-of-sample result is never used to tune rules.
    cut = max(60, int(len(d) * split))
    results = {"development": [], "out_of_sample": []}
    for i in range(60, len(d) - 17):
        sig = early_momentum(d.iloc[:i+1])
        if sig.state not in {"ENTRY_NEAR", "BUY_CONFIRMED"} or not sig.entry:
            continue
        # At earliest next candle open, then conservative stop-first order inside each OHLC candle.
        entry = float(d.open.iloc[i+1]) * (1 + slippage_bps / 10_000)
        stop, tp = float(sig.stop), float(sig.tp2)
        exit_price, outcome = float(d.close.iloc[i+16]), "timeout"
        for j in range(i+1, min(i+17, len(d))):
            candle = d.iloc[j]
            if candle.low <= stop: exit_price, outcome = stop, "stop"; break
            if candle.high >= tp: exit_price, outcome = tp, "target"; break
        gross = exit_price / entry - 1
        net = gross - 2 * fee_bps / 10_000 - 2 * slippage_bps / 10_000
        results["development" if i < cut else "out_of_sample"].append({"return": net, "outcome": outcome, "time": int(d.open_time_ms.iloc[i])})
    def metrics(trades):
        r = np.array([x["return"] for x in trades], dtype=float)
        gains, losses = r[r > 0], -r[r < 0]
        equity = np.r_[1., np.cumprod(1 + r)]
        dd = 1 - equity / np.maximum.accumulate(equity)
        return {"trades":len(trades), "win_rate_pct":float((r>0).mean()*100) if len(r) else 0., "average_win_pct":float(gains.mean()*100) if len(gains) else 0., "average_loss_pct":float(losses.mean()*100) if len(losses) else 0., "profit_factor":float(gains.sum()/losses.sum()) if losses.sum()>0 else None, "net_return_pct":float((equity[-1]-1)*100), "max_drawdown_pct":float(dd.max()*100), "assumptions":{"fee_bps_per_side":fee_bps,"slippage_bps_per_side":slippage_bps,"execution":"next candle open; stop before target if both hit"}}
    return {"candles":len(d), "available_days":round((d.open_time_ms.iloc[-1]-d.open_time_ms.iloc[0])/86_400_000,2), "development":metrics(results["development"]), "out_of_sample":metrics(results["out_of_sample"]), "automatic_trading":False}


def main():
    p=argparse.ArgumentParser();p.add_argument("input",help="JSON list of [time,o,h,l,c,v] closed Bybit candles");p.add_argument("--output",default="data/radar/backtest.json");a=p.parse_args()
    result=test_pair(json.loads(Path(a.input).read_text()))
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
if __name__ == "__main__": main()
