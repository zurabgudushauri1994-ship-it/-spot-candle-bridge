"""Long-only spot strategies from public research, expressed as target weights in [0, 1].

Per-coin strategies take one coin's daily OHLCV and return a position series; the
cross-sectional rotation takes the whole close panel and returns a weight panel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.lattia_katto import atr, rsi

DAYS = 365


def vol_scale(close: pd.Series, target: float | None, window: int = 90) -> pd.Series:
    """Target-volatility multiplier, capped at 1 (spot, no leverage)."""
    if target is None:
        return pd.Series(1.0, index=close.index)
    vol = close.pct_change().rolling(window).std() * np.sqrt(DAYS)
    return (target / vol).clip(upper=1.0).fillna(0.0)


def _hold(entry: np.ndarray, exit_: np.ndarray) -> np.ndarray:
    """Long from an entry bar until (and excluding re-entry on) an exit bar."""
    pos = np.zeros(len(entry))
    inpos = False
    for t in range(len(entry)):
        if inpos and exit_[t]:
            inpos = False
        elif not inpos and entry[t]:
            inpos = True
        pos[t] = inpos
    return pos


# ── Trend following ────────────────────────────────────────────────────────
def donchian_ensemble(df: pd.DataFrame, lookbacks=(5, 10, 20, 30, 60, 90, 150, 250, 360),
                      target_vol: float | None = 0.25) -> pd.Series:
    """Zarattini, Pagani & Barbon (2025): per lookback, enter on a close above the prior
    L-day highest close, trail a stop that ratchets up to the channel midpoint, exit on
    a close below it; average the sub-signals and size to a volatility target."""
    c = df["close"]
    cv = c.to_numpy()
    subs = []
    for L in lookbacks:
        hi = c.rolling(L).max().shift(1).to_numpy()
        mid = ((c.rolling(L).max() + c.rolling(L).min()) / 2).to_numpy()
        pos = np.zeros(len(c))
        inpos, stop = False, -np.inf
        for t in range(len(c)):
            if inpos:
                if not np.isnan(mid[t]):
                    stop = max(stop, mid[t])
                if cv[t] < stop:
                    inpos = False
            elif not np.isnan(hi[t]) and cv[t] > hi[t]:
                inpos, stop = True, mid[t]
            pos[t] = inpos
        subs.append(pos)
    sig = pd.Series(np.mean(subs, axis=0), index=c.index)
    return sig * vol_scale(c, target_vol)


def ma_trend(df: pd.DataFrame, n: int = 200, target_vol: float | None = None) -> pd.Series:
    """Time-series momentum filter: long while the close is above its n-day SMA."""
    c = df["close"]
    return (c > c.rolling(n).mean()).astype(float) * vol_scale(c, target_vol)


def ema_cross(df: pd.DataFrame, fast: int = 20, slow: int = 100, target_vol: float | None = None) -> pd.Series:
    c = df["close"]
    f, s = c.ewm(span=fast, adjust=False).mean(), c.ewm(span=slow, adjust=False).mean()
    valid = np.arange(len(c)) >= slow
    return ((f > s) & valid).astype(float) * vol_scale(c, target_vol)


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0, target_vol: float | None = None) -> pd.Series:
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    a = atr(h, l, c, n)
    hl2 = (h + l) / 2
    up, dn = hl2 - mult * a, hl2 + mult * a
    pos = np.zeros(len(c))
    trend, fup, fdn = 0, np.nan, np.nan
    for t in range(len(c)):
        if np.isnan(a[t]):
            continue
        fup = up[t] if np.isnan(fup) or c[t - 1] < fup else max(up[t], fup)
        fdn = dn[t] if np.isnan(fdn) or c[t - 1] > fdn else min(dn[t], fdn)
        if trend <= 0 and c[t] > fdn:
            trend = 1
        elif trend >= 0 and c[t] < fup:
            trend = -1
        pos[t] = trend == 1
    return pd.Series(pos, index=df.index) * vol_scale(df["close"], target_vol)


# ── Mean reversion ─────────────────────────────────────────────────────────
def rsi2(df: pd.DataFrame, buy_below: float = 10, trend_n: int = 200) -> pd.Series:
    """Connors RSI(2): buy an oversold dip inside an uptrend, exit on a close above SMA5."""
    c = df["close"]
    r = rsi(c.to_numpy(float), 2)
    sma_t, sma5 = c.rolling(trend_n).mean(), c.rolling(5).mean()
    entry = (r < buy_below) & (c > sma_t).to_numpy()
    return pd.Series(_hold(entry, (c > sma5).to_numpy()), index=c.index)


def bollinger_revert(df: pd.DataFrame, n: int = 20, k: float = 2.0, trend_n: int = 200) -> pd.Series:
    c = df["close"]
    m, sd = c.rolling(n).mean(), c.rolling(n).std()
    entry = ((c < m - k * sd) & (c > c.rolling(trend_n).mean())).to_numpy()
    return pd.Series(_hold(entry, (c > m).to_numpy()), index=c.index)


# ── Cross-sectional rotation (panel) ───────────────────────────────────────
def xs_momentum(close: pd.DataFrame, eligible: pd.DataFrame, top_k: int = 5, lookback: int = 28,
                regime: bool = True, regime_n: int = 200, btc: str = "BTCUSDT") -> pd.DataFrame:
    """Weekly: hold the top_k coins by trailing return (positive only), equal weight;
    go to cash while BTC trades below its regime_n-day SMA."""
    mom = close / close.shift(lookback) - 1
    btc_ok = close[btc] > close[btc].rolling(regime_n).mean() if regime else pd.Series(True, index=close.index)
    w = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for i, d in enumerate(close.index):
        if d.dayofweek != 6:  # rebalance on the Sunday close
            continue
        row = pd.Series(0.0, index=close.columns)
        if btc_ok.iloc[i]:
            m = mom.iloc[i][eligible.iloc[i]].dropna()
            picks = m[m > 0].nlargest(top_k).index
            row[picks] = 1.0 / top_k
        w.iloc[i] = row
    return w.ffill().fillna(0.0)
