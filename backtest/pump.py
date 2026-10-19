"""PUMP/USDT strategy search without fitting to PUMP's short history.

Rules are fixed in advance (trend rules from the research run plus a BTC regime
filter), compared first on a meme-coin basket with years of data, then checked on
PUMPUSDT, whose ~1 year of history is never used to pick a rule.

    python -m backtest.pump --out data/pump
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import fetch
from backtest import strategies as S

BASKET = ["DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT", "BONKUSDT", "WIFUSDT"]
TARGET = "PUMPUSDT"
TFS = {"1d": 1, "4h": 6, "1h": 24}
START, END = "2021-01-01", "2026-10-18"
WARMUP_DAYS = 100
COST = 0.0015


def btc_regime(btc: pd.DataFrame, n: int, k: int) -> pd.Series:
    c = btc["close"]
    return (c > c.rolling(n * k).mean()).astype(float)


def rules(k: int) -> dict:
    """Strategy name -> f(coin_df, btc_regime_series) -> position in [0, 1]."""
    own = lambda fn: (lambda df, reg: fn(df))
    return {
        "Osta ja pidä": lambda df, reg: pd.Series(1.0, index=df.index),
        "Oma trendi SMA 50": own(partial(S.ma_trend, n=50, bars_per_day=k)),
        "Oma trendi SMA 100": own(partial(S.ma_trend, n=100, bars_per_day=k)),
        "EMA 20/100": own(partial(S.ema_cross, fast=20, slow=100, bars_per_day=k)),
        "Donchian-ensemble 25 % vol": own(partial(S.donchian_ensemble, bars_per_day=k)),
        "Donchian-ensemble ilman vol-kohdetta": own(partial(S.donchian_ensemble, target_vol=None, bars_per_day=k)),
        "BTC-suodin (BTC > SMA 100)": lambda df, reg: reg,
        "BTC-suodin + oma SMA 50": lambda df, reg: reg * S.ma_trend(df, n=50, bars_per_day=k),
    }


def backtest(df: pd.DataFrame, pos: pd.Series, k: int, start: pd.Timestamp, cost: float) -> dict:
    o = df["open"].to_numpy(float)
    r_oo = np.r_[o[1:] / o[:-1] - 1, 0.0]          # bar t: open t -> open t+1
    p = pos.fillna(0.0).to_numpy(float)
    held = np.r_[0.0, p[:-1]]                         # decided at close t-1, held over bar t
    ret = held * r_oo - cost * np.abs(np.diff(np.r_[0.0, held]))
    s = pd.Series(ret, index=df.index).loc[start:]
    h = pd.Series(held, index=df.index).loc[start:]
    if len(s) < 30:
        return {}
    eq = (1 + s).cumprod()
    per_year = S.DAYS * k
    years = len(s) / per_year
    sd = s.std()
    entries = int(((h > 0) & (h.shift(1).fillna(0) == 0)).sum())
    return dict(total=float(eq.iloc[-1] - 1) * 100,
                cagr=float(eq.iloc[-1] ** (1 / years) - 1) * 100 if years >= 0.5 and eq.iloc[-1] > 0 else None,
                sharpe=float(s.mean() / sd * np.sqrt(per_year)) if sd > 0 else None,
                max_dd=float((eq / eq.cummax() - 1).min()) * 100,
                exposure=float(h.mean()) * 100, entries=entries, years=float(years),
                now=float(p[-1]))


def load(sym: str, tf: str, cache: Path) -> pd.DataFrame:
    df, src = fetch.load(sym, tf, START, END, cache)
    print(f"{sym} {tf}: {len(df)} bars from {src}", flush=True)
    if df.empty:
        return df
    return df.assign(dt=pd.to_datetime(df["time"], unit="ms")).set_index("dt")


def f(x, d=1):
    return "–" if x is None else f"{x:.{d}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/pump")
    ap.add_argument("--cache", default=".cache/candles")
    args = ap.parse_args()
    out, cache = Path(args.out), Path(args.cache)
    out.mkdir(parents=True, exist_ok=True)

    syms = BASKET + [TARGET, "BTCUSDT"]
    jobs = [(s, tf) for s in syms for tf in TFS]
    with ThreadPoolExecutor(max_workers=12) as pool:
        data = dict(zip(jobs, pool.map(lambda j: load(j[0], j[1], cache), jobs)))

    res: dict = {}
    for tf, k in TFS.items():
        btc = data[("BTCUSDT", tf)]
        for sym in BASKET + [TARGET]:
            df = data[(sym, tf)]
            if len(df) < (WARMUP_DAYS + 60) * k:
                continue
            reg = btc_regime(btc, 100, k).reindex(df.index, method="ffill").fillna(0.0)
            start = df.index[WARMUP_DAYS * k]
            for name, rule in rules(k).items():
                pos = rule(df, reg)
                res[(tf, sym, name)] = backtest(df, pos, k, start, COST)
                if sym == TARGET:
                    res[(tf, sym, name + " (kulut 0,30 %)")] = backtest(df, pos, k, start, 0.003)
            res[(tf, sym, "_last")] = dict(time=str(df.index[-1]), close=float(df["close"].iloc[-1]))

    names = list(rules(1))
    md = ["# PUMP/USDT — strategiahaku", "",
          f"Säännöt valittu etukäteen. Ne verrataan ensin meemikolikkokoriin ({', '.join(BASKET)}), jolla on vuosien historia, "
          f"ja vasta sitten tarkistetaan {TARGET}:lla. Kulut {COST * 100:.2f} % per kauppa, kauppa seuraavan kynttilän avauksessa. "
          f"Ensimmäiset {WARMUP_DAYS} päivää jokaiselta kolikolta ovat lämmittelyä.", ""]
    summary = []
    for tf in TFS:
        md += [f"## Meemikori — {tf}", "",
               "| Strategia | Mediaani-Sharpe | Kolikoita Sharpe > osta&pidä | Kolikoita voitolla | Mediaani max DD % |", "|---|---|---|---|---|"]
        for name in names:
            rows = [res.get((tf, s, name)) for s in BASKET]
            bh = [res.get((tf, s, "Osta ja pidä")) for s in BASKET]
            pairs = [(r, b) for r, b in zip(rows, bh) if r and b and r.get("sharpe") is not None and b.get("sharpe") is not None]
            if not pairs:
                continue
            sh = float(np.median([r["sharpe"] for r, _ in pairs]))
            beat = sum(1 for r, b in pairs if r["sharpe"] > b["sharpe"])
            win = sum(1 for r, _ in pairs if r["total"] > 0)
            dd = float(np.median([r["max_dd"] for r, _ in pairs]))
            summary.append(dict(tf=tf, name=name, median_sharpe=sh, beat=beat, win=win, n=len(pairs), median_dd=dd))
            md.append(f"| {name} | {f(sh, 2)} | {beat}/{len(pairs)} | {win}/{len(pairs)} | {f(dd)} |")
        md += ["", f"## {TARGET} — {tf}", "",
               "| Strategia | Tuotto yht. % | Sharpe | Max DD % | Altistus % | Kauppoja | Signaali nyt |", "|---|---|---|---|---|---|---|"]
        for name in names + [n + " (kulut 0,30 %)" for n in names if n != "Osta ja pidä"]:
            r = res.get((tf, TARGET, name))
            if r:
                md.append(f"| {name} | {f(r['total'])} | {f(r['sharpe'], 2)} | {f(r['max_dd'])} | {f(r['exposure'], 0)} | {r['entries']} "
                          f"| {'🟢 sisällä' if r['now'] > 0 else '🔴 ulkona'} |")
        last = res.get((tf, TARGET, "_last"))
        if last:
            md += ["", f"Viimeisin {TARGET} {tf} -kynttilä: {last['time']} UTC, päätöskurssi {last['close']}", ""]
        md.append("")
    (out / "report.md").write_text("\n".join(md) + "\n")
    (out / "results.json").write_text(json.dumps(dict(summary=summary, runs={" | ".join(k): v for k, v in res.items()}), indent=1))
    print("\n".join(md))


if __name__ == "__main__":
    main()
