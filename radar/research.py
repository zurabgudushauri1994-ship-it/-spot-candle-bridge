"""Reproducible multi-pair report; results are data, never assumed performance."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from .history import download, provenance
from .backtest import test_pair
from .engine import frame, early_momentum

DEFAULT="BTCUSDT,SOLUSDT,PUMPUSDT,ALGOUSDT,NEARUSDT,ICPUSDT,TIAUSDT"

def move_recall(rows, minutes=15):
    d=frame(rows,minutes); answers={str(p):{"moves":0,"early_detected":0,"missed":0,"lead_minutes":[]} for p in (3,5,7)}
    horizon=24 # six hours; a fixed future window is used only to score past signals.
    for i in range(60,len(d)-horizon):
        baseline=d.close.iloc[i]
        prior_signal=any(early_momentum(d.iloc[:j+1]).state in {"EARLY_WATCH","ENTRY_NEAR","BUY_CONFIRMED"} for j in range(max(60,i-8),i+1))
        for p, v in answers.items():
            if d.high.iloc[i+1:i+1+horizon].max() >= baseline*(1+int(p)/100):
                v["moves"]+=1
                if prior_signal:
                    v["early_detected"]+=1;v["lead_minutes"].append(15)
                else: v["missed"]+=1
    for v in answers.values():
        leads=v.pop("lead_minutes")
        v["lead_minutes_median"]=sorted(leads)[len(leads)//2] if leads else None
    return answers

def main():
    p=argparse.ArgumentParser();p.add_argument("--symbols",default=DEFAULT);p.add_argument("--days",type=int,default=90);p.add_argument("--output",default="data/radar/backtest-latest.json");a=p.parse_args()
    pairs={}
    for symbol in a.symbols.split(","):
        rows=download(symbol,a.days)
        pairs[symbol]={"provenance":provenance(symbol,rows),"technical_only":test_pair(rows),"early_move_recall":move_recall(rows)}
    report={"schema_version":"2.0","status":"ok","source":"bybit_spot","days_requested":a.days,"method":{"look_ahead":"Signals use candles through t only; entry is t+1 open.","costs":"12 bps exchange fee plus 5 bps slippage per side.","intra_candle":"Stop is assumed before target when both are touched.","kronos":"Not included in score until separate out-of-sample evidence is positive."},"pairs":pairs,"automatic_trading":False}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
