"""Second-round checks for the strategy research shortlist: portfolio-level volatility
targeting for the Donchian ensemble, single-asset trend parameter plateaus, cost stress,
rolling one-year windows and a two-sleeve blend.

    python -m backtest.robustness --out data/strategy-research
"""
from __future__ import annotations

import argparse
import json
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import research as R
from backtest import strategies as S


def vol_target(w: pd.DataFrame, target: float, window: int = 60) -> pd.DataFrame:
    """Scale a weight panel to a portfolio volatility target (estimated from returns
    already known at the decision close), never above 100 % gross exposure."""
    raw, gross = R.portfolio_returns(w, R.PANEL["r_oo"])
    vol = raw.shift(1).rolling(window).std() * np.sqrt(S.DAYS)
    scale = (target / vol).fillna(1.0)
    cap = (1.0 / gross.replace(0, np.nan)).fillna(np.inf)
    return w.mul(np.minimum(scale, cap), axis=0)


def single(fn, coin: str) -> pd.DataFrame:
    pos, _ = R.coin_weights(fn, [coin])
    return pos


def run(label: str, w: pd.DataFrame, cost: float = R.COST) -> dict:
    old, R.COST = R.COST, cost
    try:
        ret, expo = R.portfolio_returns(w, R.PANEL["r_oo"].reindex(columns=w.columns))
    finally:
        R.COST = old
    return dict(name=label, ret=ret, expo=expo)


def rolling_year(ret: pd.Series) -> dict:
    eq = (1 + ret).cumprod()
    yr = (eq / eq.shift(S.DAYS) - 1).dropna()
    yr = yr[yr.index >= pd.Timestamp("2020-01-01")]   # skip the warm-up year
    return dict(pos_pct=float((yr > 0).mean() * 100), worst=float(yr.min() * 100), median=float(yr.median() * 100))


def table(rows: list[dict]) -> list[str]:
    head = ["| Strategia | CAGR % | Sharpe | Max DD % | Altistus % | IS CAGR / Sharpe | OOS CAGR / Sharpe "
            "| Julkaisun jälkeen CAGR / Sharpe | 12 kk ikkunoista voitolla % | Huonoin 12 kk % |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    out = []
    for r in rows:
        p = {k: R.stats(r["ret"], r["expo"], a, b) for k, (a, b) in R.PERIODS.items()}
        ry = rolling_year(r["ret"])
        r.update(periods=p, rolling=ry, yearly=R.yearly(r["ret"]))
        k, i, o, j = (p[n] for n in R.PERIODS)
        out.append(f"| {r['name']} | {R.f(k['cagr'])} | {R.f(k['sharpe'], 2)} | {R.f(k['max_dd'])} | {R.f(k['exposure'], 0)} "
                   f"| {R.f(i['cagr'])} / {R.f(i['sharpe'], 2)} | {R.f(o['cagr'])} / {R.f(o['sharpe'], 2)} "
                   f"| {R.f(j['cagr'])} / {R.f(j['sharpe'], 2)} | {R.f(ry['pos_pct'], 0)} | {R.f(ry['worst'])} |")
    return head + out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/strategy-research")
    ap.add_argument("--cache", default=".cache/candles")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    R.load_panel(Path(args.cache))

    _, don_w = R.coin_weights(S.donchian_ensemble)
    _, bh_w = R.coin_weights(None)
    sections: dict[str, list[dict]] = {}

    sections["A. Donchian-ensemble salkkutason volatiliteettikohteella"] = [
        run("Donchian-ensemble, ei salkkukohdetta", don_w),
        *[run(f"Donchian-ensemble, salkku {int(t * 100)} % vol", vol_target(don_w, t)) for t in (0.20, 0.30, 0.40)],
        run("Donchian-ensemble, salkku 30 % vol, kulut 0,30 %", vol_target(don_w, 0.30), cost=0.003),
        run("Osta ja pidä (tasapaino)", bh_w),
    ]

    for coin in ("BTCUSDT", "ETHUSDT"):
        rows = [run(f"{coin} osta ja pidä", single(None, coin))]
        rows += [run(f"{coin} SMA {n}", single(partial(S.ma_trend, n=n), coin)) for n in (50, 75, 100, 125, 150, 200)]
        rows += [run(f"{coin} SMA 100, kulut 0,30 %", single(partial(S.ma_trend, n=100), coin), cost=0.003),
                 run(f"{coin} EMA 20/100", single(partial(S.ema_cross, fast=20, slow=100), coin)),
                 run(f"{coin} Donchian-ensemble 25 % vol", single(S.donchian_ensemble, coin)),
                 run(f"{coin} Donchian-ensemble ilman vol-kohdetta", single(partial(S.donchian_ensemble, target_vol=None), coin))]
        sections[f"B. Yhden kolikon trendi — {coin}"] = rows

    don30 = run("x", vol_target(don_w, 0.30))["ret"]
    btc100 = run("x", single(partial(S.ma_trend, n=100), "BTCUSDT"))["ret"]
    expo_d = vol_target(don_w, 0.30).sum(axis=1)
    expo_b = single(partial(S.ma_trend, n=100), "BTCUSDT").sum(axis=1)
    sections["C. Yhdistelmä"] = [
        dict(name="50 % Donchian-salkku 30 % vol + 50 % BTC SMA 100", ret=0.5 * don30 + 0.5 * btc100, expo=0.5 * expo_d + 0.5 * expo_b),
    ]

    md = ["# Strategiatutkimus — vaihe 2: kestävyystestit", "",
          "Samat säännöt ja kulut kuin vaiheessa 1. Kolikkokohtaiset painot vaiheesta 1, salkkutason vol-kohde arvioidaan "
          "60 päivän toteutuneesta volatiliteetista ilman tulevaisuuden tietoa ja rajataan 100 %:n bruttoaltistukseen.", ""]
    dump = {}
    for title, rows in sections.items():
        md += [f"## {title}", "", *table(rows), ""]
        dump[title] = [dict(name=r["name"], periods=r["periods"], rolling=r["rolling"], yearly=r["yearly"]) for r in rows]
    years = sorted({y for rows in sections.values() for r in rows for y in r["yearly"]})
    md += ["## Vuosituotot %", "", "| Strategia | " + " | ".join(years) + " |", "|---|" + "---|" * len(years)]
    for rows in sections.values():
        for r in rows:
            md.append(f"| {r['name']} | " + " | ".join(R.f(r["yearly"].get(y)) for y in years) + " |")
    (out / "robustness.md").write_text("\n".join(md) + "\n")
    (out / "robustness.json").write_text(json.dumps(dump, indent=1))
    print("\n".join(md))


if __name__ == "__main__":
    main()
