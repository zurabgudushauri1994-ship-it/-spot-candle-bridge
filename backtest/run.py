"""Broad backtest of the Lattia & Katto v3 strategy: symbols x timeframes x level modes,
filter ablations, one-at-a-time parameter sensitivity and an in/out-of-sample split.

    python -m backtest.run --out data/lattia-katto
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import fetch
from backtest.lattia_katto import Params, metrics, r_stats, run

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
           "LINKUSDT", "NEARUSDT", "SUIUSDT", "PEPEUSDT", "WIFUSDT", "TIAUSDT", "ICPUSDT", "ALGOUSDT", "PUMPUSDT"]
BASE_TFS = ["15m", "1h", "4h", "1d"]
STUDY_TFS = ["1h", "4h"]
MODES = ["auto", "pivot"]
START, END = "2023-01-01", "2026-10-18"
SPLIT = "2025-01-01"  # in-sample before, out-of-sample after

ABLATIONS = {
    "trend_on": dict(use_trend=True),
    "be_off": dict(be_rr=0.0),
    "vol_off": dict(use_vol=False),
    "cooldown_0": dict(cooldown=0),
    "no_costs": dict(commission_pct=0.0, slippage_pct=0.0),
    "risk_1pct": dict(size_mode="risk"),
}
SENSITIVITY = {
    "auto_len": [20, 100], "piv_len": [5, 20], "zone_atr": [0.25, 1.0],
    "sl_b_atr": [0.5, 1.5, 2.0], "sl_m_atr": [0.5, 1.5, 2.0], "tp_m_rr": [1.5, 4.0],
    "min_rr": [1.0, 2.0], "be_rr": [0.5, 2.0], "vol_mult": [1.0, 2.0],
}

DATA: dict[tuple[str, str], pd.DataFrame] = {}
SPLIT_MS = int(pd.Timestamp(SPLIT, tz="UTC").timestamp() * 1000)


def job(spec: tuple) -> dict:
    sym, tf, mode, variant, overrides = spec
    df = DATA[(sym, tf)]
    p = Params(level_mode=mode).with_(**overrides)
    trades, equity = run(df, p)
    m = metrics(df, trades, equity, p)
    m["is"] = r_stats([t for t in trades if t["entry_time"] < SPLIT_MS])
    m["oos"] = r_stats([t for t in trades if t["entry_time"] >= SPLIT_MS])
    return dict(symbol=sym, tf=tf, mode=mode, variant=variant, metrics=m, trades=trades)


def specs() -> list[tuple]:
    out = []
    for (sym, tf) in DATA:
        for mode in MODES:
            if tf in BASE_TFS:
                out.append((sym, tf, mode, "base", {}))
            if tf not in STUDY_TFS:
                continue
            for name, ov in ABLATIONS.items():
                out.append((sym, tf, mode, name, ov))
            for key, values in SENSITIVITY.items():
                if (key == "auto_len" and mode != "auto") or (key == "piv_len" and mode != "pivot"):
                    continue
                for v in values:
                    out.append((sym, tf, mode, f"{key}={v}", {key: v}))
    return out


def pooled(rows: list[dict]) -> dict:
    trades = [t for r in rows for t in r["trades"]]
    rets = [r["metrics"]["ret_pct"] for r in rows if r["metrics"]["trades"] > 0]
    dds = [r["metrics"]["max_dd_pct"] for r in rows if r["metrics"]["trades"] > 0]
    out = r_stats(trades)
    out.update(markets=len(rows), profitable=sum(1 for x in rets if x > 0), traded=len(rets),
               median_ret_pct=float(np.median(rets)) if rets else None,
               mean_dd_pct=float(np.mean(dds)) if dds else None,
               is_=r_stats([t for t in trades if t["entry_time"] < SPLIT_MS]),
               oos=r_stats([t for t in trades if t["entry_time"] >= SPLIT_MS]),
               Pomppu=r_stats([t for t in trades if t["type"] == "Pomppu"]),
               Murto=r_stats([t for t in trades if t["type"] == "Murto"]))
    return out


# ── Markdown ───────────────────────────────────────────────────────────────
def f(x, d=2, suffix=""):
    return "–" if x is None else f"{x:.{d}f}{suffix}"


def pool_row(label: str, s: dict) -> str:
    return (f"| {label} | {s['trades']} | {f(s['win_pct'], 1)} | {f(s['pf'])} | {f(s['avg_r'], 3)} | {f(s['total_r'], 1)} "
            f"| {f(s['t_stat'])} | {s['profitable']}/{s['traded']} | {f(s['median_ret_pct'], 1)} | {f(s['mean_dd_pct'], 1)} |")


POOL_HEAD = ("| Ryhmä | Kaupat | Voitto-% | PF | Keski-R | Yht. R | t | Voitollisia | Mediaanituotto % | Keski-DD % |\n"
             "|---|---|---|---|---|---|---|---|---|---|")


def report(results: list[dict], sources: dict, elapsed: float) -> str:
    by = {}
    for r in results:
        by.setdefault((r["tf"], r["mode"], r["variant"]), []).append(r)
    L = ["# Lattia & Katto v3 — laaja backtest", "",
         f"Jakso {START} → {END} · {len(sources)} markkinaa · {len(results)} ajoa · ajoaika {elapsed:.0f} s", "",
         "Oletusasetukset kuten Pine-skriptissä: 10 % pääomasta per kauppa, kulut 0,1 % per suunta + 0,02 % slippage.",
         f"R = nettotulos jaettuna alkuperäisellä riskillä (kulut mukana). IS = ennen {SPLIT}, OOS = {SPLIT} jälkeen.", "",
         "## 1. Perusasetukset: aikaväli × tasojen lähde", "", POOL_HEAD]
    for tf in BASE_TFS:
        for mode in MODES:
            rows = by.get((tf, mode, "base"))
            if rows:
                L.append(pool_row(f"{tf} {mode}", pooled(rows)))
    L += ["", "## 2. Signaalityypit ja IS/OOS (perusasetukset)", "",
          "| Ryhmä | Pomppu: kaupat / keski-R / PF | Murto: kaupat / keski-R / PF | IS: kaupat / keski-R | OOS: kaupat / keski-R |",
          "|---|---|---|---|---|"]
    for tf in BASE_TFS:
        for mode in MODES:
            rows = by.get((tf, mode, "base"))
            if not rows:
                continue
            s = pooled(rows)
            b, m, i, o = s["Pomppu"], s["Murto"], s["is_"], s["oos"]
            L.append(f"| {tf} {mode} | {b['trades']} / {f(b['avg_r'], 3)} / {f(b['pf'])} | {m['trades']} / {f(m['avg_r'], 3)} / {f(m['pf'])} "
                     f"| {i['trades']} / {f(i['avg_r'], 3)} | {o['trades']} / {f(o['avg_r'], 3)} |")
    for tf in STUDY_TFS:
        for mode in MODES:
            L += ["", f"## 3. Suodattimet ja muunnelmat — {tf} {mode}", "", POOL_HEAD]
            L.append(pool_row("base", pooled(by[(tf, mode, "base")])))
            for name in ABLATIONS:
                if (tf, mode, name) in by:
                    L.append(pool_row(name, pooled(by[(tf, mode, name)])))
            L += ["", f"### Parametriherkkyys — {tf} {mode}", "", POOL_HEAD]
            for key, values in SENSITIVITY.items():
                for v in values:
                    k = (tf, mode, f"{key}={v}")
                    if k in by:
                        L.append(pool_row(f"{key}={v}", pooled(by[k])))
    for tf in BASE_TFS:
        for mode in MODES:
            rows = sorted(by.get((tf, mode, "base"), []), key=lambda r: r["symbol"])
            if not rows:
                continue
            L += ["", f"## 4. Markkinakohtaiset — {tf} {mode}", "",
                  "| Symboli | Vuosia | Kaupat | Voitto-% | PF | Keski-R | Tuotto % | Max DD % | Buy&hold % | Altistus % |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for r in rows:
                m = r["metrics"]
                L.append(f"| {r['symbol']} | {f(m['years'], 1)} | {m['trades']} | {f(m['win_pct'], 1)} | {f(m['pf'])} | {f(m['avg_r'], 3)} "
                         f"| {f(m['ret_pct'], 1)} | {f(m['max_dd_pct'], 1)} | {f(m['bh_pct'], 0)} | {f(m['exposure_pct'], 1)} |")
    L += ["", "## Datalähteet", "", "| Markkina | Lähde | Kynttilöitä |", "|---|---|---|"]
    for (sym, tf), (src, n) in sorted(sources.items()):
        L.append(f"| {sym} {tf} | {src} | {n} |")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/lattia-katto")
    ap.add_argument("--cache", default=".cache/candles")
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    args = ap.parse_args()
    t0 = time.time()
    out, cache = Path(args.out), Path(args.cache)
    out.mkdir(parents=True, exist_ok=True)

    sources = {}
    for sym in args.symbols.split(","):
        for tf in BASE_TFS:
            df, src = fetch.load(sym, tf, START, END, cache)
            print(f"{sym} {tf}: {len(df)} bars from {src}", flush=True)
            if len(df) >= 400:
                DATA[(sym, tf)] = df
                sources[(sym, tf)] = (src, len(df))

    work = specs()
    print(f"{len(work)} backtest runs", flush=True)
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        results = list(pool.map(job, work, chunksize=8))

    elapsed = time.time() - t0
    (out / "report.md").write_text(report(results, sources, elapsed))
    summary = [dict(symbol=r["symbol"], tf=r["tf"], mode=r["mode"], variant=r["variant"], **r["metrics"]) for r in results]
    (out / "results.json").write_text(json.dumps(dict(start=START, end=END, split=SPLIT, runs=summary,
                                                      sources={f"{k[0]} {k[1]}": v for k, v in sources.items()}), indent=1))
    base_trades = [dict(symbol=r["symbol"], tf=r["tf"], mode=r["mode"], **t) for r in results if r["variant"] == "base" for t in r["trades"]]
    pd.DataFrame(base_trades).to_csv(out / "trades_base.csv.gz", index=False, compression="gzip")
    print(f"done in {elapsed:.0f}s", flush=True)


if __name__ == "__main__":
    main()
