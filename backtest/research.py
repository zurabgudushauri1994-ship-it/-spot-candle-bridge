"""Strategy research: published long-only crypto strategies on a daily coin panel.

Weights are decided on the daily close and traded at the next open; costs are charged
on every change of weight. Per-coin strategies run as an equal-weight portfolio over
coins with at least a year of history.

    python -m backtest.research --out data/strategy-research
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import fetch
from backtest import strategies as S

COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "SOLUSDT", "DOTUSDT", "LTCUSDT",
         "LINKUSDT", "AVAXUSDT", "TRXUSDT", "ATOMUSDT", "ETCUSDT", "XLMUSDT", "BCHUSDT", "UNIUSDT", "FILUSDT",
         "NEARUSDT", "ALGOUSDT", "ICPUSDT", "AAVEUSDT", "SUIUSDT", "PEPEUSDT", "WIFUSDT", "TIAUSDT"]
START, END = "2019-01-01", "2026-10-18"
PERIODS = {"Koko": ("2019-01-01", END), "IS 2019–22": ("2019-01-01", "2022-12-31"),
           "OOS 2023–26": ("2023-01-01", END), "Julkaisun jälkeen": ("2025-04-01", END)}
COST = 0.0015       # 0.10 % fee + 0.05 % slippage per unit of turnover
MIN_HISTORY = 365   # a coin joins the portfolio after a year of trading

PER_COIN = {
    "Donchian-ensemble (25 % vol)": partial(S.donchian_ensemble),
    "Donchian-ensemble (15 % vol)": partial(S.donchian_ensemble, target_vol=0.15),
    "Donchian-ensemble (40 % vol)": partial(S.donchian_ensemble, target_vol=0.40),
    "Donchian-ensemble (ei vol-kohdetta)": partial(S.donchian_ensemble, target_vol=None),
    "Donchian lyhyet 5–30": partial(S.donchian_ensemble, lookbacks=(5, 10, 20, 30)),
    "Donchian pitkät 60–360": partial(S.donchian_ensemble, lookbacks=(60, 90, 150, 250, 360)),
    "SMA 50 trendi": partial(S.ma_trend, n=50),
    "SMA 100 trendi": partial(S.ma_trend, n=100),
    "SMA 150 trendi": partial(S.ma_trend, n=150),
    "SMA 200 trendi": partial(S.ma_trend, n=200),
    "SMA 100 trendi (25 % vol)": partial(S.ma_trend, n=100, target_vol=0.25),
    "EMA 10/50": partial(S.ema_cross, fast=10, slow=50),
    "EMA 20/100": partial(S.ema_cross, fast=20, slow=100),
    "EMA 50/200": partial(S.ema_cross, fast=50, slow=200),
    "EMA 20/100 (25 % vol)": partial(S.ema_cross, fast=20, slow=100, target_vol=0.25),
    "Supertrend 10/3": partial(S.supertrend, n=10, mult=3.0),
    "Supertrend 20/4": partial(S.supertrend, n=20, mult=4.0),
    "RSI-2 < 5": partial(S.rsi2, buy_below=5),
    "RSI-2 < 10": partial(S.rsi2, buy_below=10),
    "RSI-2 < 15": partial(S.rsi2, buy_below=15),
    "Bollinger 20/2 paluu": partial(S.bollinger_revert, k=2.0),
    "Bollinger 20/2.5 paluu": partial(S.bollinger_revert, k=2.5),
    "Osta ja pidä (tasapaino)": None,
}
XS = {
    "Rotaatio top 5 / 28 pv + BTC-suodin": dict(top_k=5, lookback=28),
    "Rotaatio top 3 / 28 pv + BTC-suodin": dict(top_k=3, lookback=28),
    "Rotaatio top 10 / 28 pv + BTC-suodin": dict(top_k=10, lookback=28),
    "Rotaatio top 5 / 14 pv + BTC-suodin": dict(top_k=5, lookback=14),
    "Rotaatio top 5 / 56 pv + BTC-suodin": dict(top_k=5, lookback=56),
    "Rotaatio top 5 / 28 pv ilman suodinta": dict(top_k=5, lookback=28, regime=False),
}

PANEL: dict[str, pd.DataFrame] = {}


# ── Engine ─────────────────────────────────────────────────────────────────
def portfolio_returns(w: pd.DataFrame, r_oo: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """w decided at close t earns r_oo on bar t+1 (next open -> following open)."""
    w = w.fillna(0.0)
    gross = (w.shift(1) * r_oo).sum(axis=1)
    turnover = w.diff().abs().sum(axis=1).shift(1).fillna(0.0)
    return gross - COST * turnover, w.sum(axis=1)


def stats(ret: pd.Series, expo: pd.Series, start: str, end: str) -> dict:
    r = ret.loc[start:end]
    if len(r) < 30:
        return {}
    eq = (1 + r).cumprod()
    years = len(r) / S.DAYS
    sd = r.std()
    down = r[r < 0].std()
    dd = float((eq / eq.cummax() - 1).min())
    cagr = float(eq.iloc[-1] ** (1 / years) - 1)
    return dict(cagr=cagr * 100, vol=float(sd * np.sqrt(S.DAYS) * 100),
                sharpe=float(r.mean() / sd * np.sqrt(S.DAYS)) if sd > 0 else None,
                sortino=float(r.mean() / down * np.sqrt(S.DAYS)) if down > 0 else None,
                max_dd=dd * 100, calmar=cagr / -dd if dd < 0 else None,
                exposure=float(expo.loc[start:end].mean() * 100), total=float(eq.iloc[-1] - 1) * 100)


def yearly(ret: pd.Series) -> dict:
    return {str(y): float((1 + g).prod() - 1) * 100 for y, g in ret.groupby(ret.index.year)}


def per_coin_job(name: str) -> dict:
    close, r_oo, eligible = PANEL["close"], PANEL["r_oo"], PANEL["eligible"]
    fn = PER_COIN[name]
    pos = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for coin in close.columns:
        df = PANEL["ohlc"][coin]
        pos.loc[df.index, coin] = 1.0 if fn is None else fn(df).fillna(0.0).to_numpy()
    pos = pos.where(eligible, 0.0)
    n_active = eligible.sum(axis=1).replace(0, np.nan)
    w = pos.div(n_active, axis=0).fillna(0.0)
    ret, expo = portfolio_returns(w, r_oo)
    coins = {}
    for coin in close.columns:   # each coin on its own, full capital, after its first year
        first = eligible[coin].idxmax() if eligible[coin].any() else None
        if first is None:
            continue
        cr, ce = portfolio_returns(pos[[coin]], r_oo[[coin]])
        bh, _ = portfolio_returns(eligible[[coin]].astype(float), r_oo[[coin]])
        s, b = stats(cr, ce, str(first.date()), END), stats(bh, ce, str(first.date()), END)
        if s:
            coins[coin] = dict(cagr=s["cagr"], sharpe=s["sharpe"], max_dd=s["max_dd"],
                               bh_cagr=b["cagr"], bh_sharpe=b["sharpe"], bh_dd=b["max_dd"])
    return dict(name=name, kind="per_coin", ret=ret, expo=expo, coins=coins)


def xs_job(name: str) -> dict:
    w = S.xs_momentum(PANEL["close"], PANEL["eligible"], **XS[name])
    ret, expo = portfolio_returns(w, PANEL["r_oo"])
    return dict(name=name, kind="rotation", ret=ret, expo=expo, coins={})


def btc_only(fn, label: str) -> dict:
    df = PANEL["ohlc"]["BTCUSDT"]
    close = PANEL["close"][["BTCUSDT"]]
    pos = pd.DataFrame(0.0, index=close.index, columns=["BTCUSDT"])
    pos.loc[df.index, "BTCUSDT"] = 1.0 if fn is None else fn(df).fillna(0.0).to_numpy()
    ret, expo = portfolio_returns(pos, PANEL["r_oo"][["BTCUSDT"]])
    return dict(name=label, kind="btc", ret=ret, expo=expo, coins={})


# ── Report ─────────────────────────────────────────────────────────────────
def f(x, d=1):
    return "–" if x is None else f"{x:.{d}f}"


def build(results: list[dict]) -> tuple[list[dict], str]:
    rows = []
    for r in results:
        per = {k: stats(r["ret"], r["expo"], a, b) for k, (a, b) in PERIODS.items()}
        coins = r["coins"]
        beat = sum(1 for c in coins.values() if c["sharpe"] is not None and c["bh_sharpe"] is not None and c["sharpe"] > c["bh_sharpe"])
        pos = sum(1 for c in coins.values() if c["cagr"] > 0)
        rows.append(dict(name=r["name"], kind=r["kind"], periods=per, yearly=yearly(r["ret"]), coins=coins,
                         coins_positive=pos, coins_beat_bh_sharpe=beat, n_coins=len(coins)))
    rows.sort(key=lambda x: -(x["periods"]["Koko"].get("sharpe") or -9))

    L = ["# Strategiatutkimus — julkaistut long-only-kryptostrategiat", "",
         f"Päivädata {START} → {END}, {len(COINS)} Binance-spot-kolikkoa. Kulut {COST * 100:.2f} % per kaupattu osuus "
         "(0,10 % palkkio + 0,05 % slippage). Signaali päätöskurssista, kauppa seuraavan päivän avauksessa.",
         "Kolikko tulee mukaan vuoden kaupankäynnin jälkeen. Per-kolikko-strategiat = tasapainotettu salkku kaikista mukana olevista.",
         "", "## Yhteenveto (järjestys: koko jakson Sharpe)", "",
         "| Strategia | CAGR % | Sharpe | Max DD % | Calmar | Altistus % | IS CAGR / Sharpe | OOS CAGR / Sharpe | Julkaisun jälkeen CAGR / Sharpe | Kolikoita voitolla | Sharpe > osta&pidä |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in rows:
        k, i, o, p = (x["periods"].get(n, {}) for n in PERIODS)
        cn = f"{x['coins_positive']}/{x['n_coins']}" if x["n_coins"] else "–"
        cb = f"{x['coins_beat_bh_sharpe']}/{x['n_coins']}" if x["n_coins"] else "–"
        L.append(f"| {x['name']} | {f(k.get('cagr'))} | {f(k.get('sharpe'), 2)} | {f(k.get('max_dd'))} | {f(k.get('calmar'), 2)} "
                 f"| {f(k.get('exposure'), 0)} | {f(i.get('cagr'))} / {f(i.get('sharpe'), 2)} | {f(o.get('cagr'))} / {f(o.get('sharpe'), 2)} "
                 f"| {f(p.get('cagr'))} / {f(p.get('sharpe'), 2)} | {cn} | {cb} |")
    years = sorted({y for x in rows for y in x["yearly"]})
    L += ["", "## Vuosituotot %", "", "| Strategia | " + " | ".join(years) + " |", "|---|" + "---|" * len(years)]
    for x in rows:
        L.append(f"| {x['name']} | " + " | ".join(f(x["yearly"].get(y)) for y in years) + " |")
    for x in rows[:6]:
        if not x["coins"]:
            continue
        L += ["", f"## Kolikkokohtaisesti — {x['name']}", "",
              "| Kolikko | CAGR % | Sharpe | Max DD % | Osta&pidä CAGR % | Osta&pidä Sharpe | Osta&pidä DD % |", "|---|---|---|---|---|---|---|"]
        for coin, c in sorted(x["coins"].items()):
            L.append(f"| {coin} | {f(c['cagr'])} | {f(c['sharpe'], 2)} | {f(c['max_dd'])} | {f(c['bh_cagr'])} | {f(c['bh_sharpe'], 2)} | {f(c['bh_dd'])} |")
    return rows, "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/strategy-research")
    ap.add_argument("--cache", default=".cache/candles")
    args = ap.parse_args()
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=12) as pool:
        loaded = list(pool.map(lambda c: (c, *fetch.load(c, "1d", START, END, Path(args.cache))), COINS))
    ohlc = {}
    for coin, df, src in loaded:
        print(f"{coin}: {len(df)} days from {src}", flush=True)
        if len(df) > MIN_HISTORY + 30:
            df = df.assign(date=pd.to_datetime(df["time"], unit="ms").dt.normalize()).set_index("date")
            ohlc[coin] = df[["open", "high", "low", "close", "volume"]]
    close = pd.DataFrame({c: d["close"] for c, d in ohlc.items()}).sort_index()
    opn = pd.DataFrame({c: d["open"] for c, d in ohlc.items()}).reindex(close.index)
    PANEL.update(ohlc=ohlc, close=close,
                 r_oo=(opn.shift(-1) / opn - 1).fillna(0.0),
                 eligible=close.notna() & (close.notna().cumsum() > MIN_HISTORY))

    with ProcessPoolExecutor() as pool:
        results = list(pool.map(per_coin_job, PER_COIN)) + list(pool.map(xs_job, XS))
    results += [btc_only(None, "BTC osta ja pidä"), btc_only(S.donchian_ensemble, "BTC Donchian-ensemble (25 % vol)"),
                btc_only(partial(S.ma_trend, n=100), "BTC SMA 100 trendi")]

    rows, md = build(results)
    md += f"\nAjoaika {time.time() - t0:.0f} s.\n"
    (out / "report.md").write_text(md)
    (out / "results.json").write_text(json.dumps(dict(start=START, end=END, cost=COST, periods=PERIODS, strategies=rows), indent=1))
    pd.DataFrame({r["name"]: r["ret"] for r in results}).to_csv(out / "daily_returns.csv.gz", compression="gzip")
    print(md[:4000])


if __name__ == "__main__":
    main()
