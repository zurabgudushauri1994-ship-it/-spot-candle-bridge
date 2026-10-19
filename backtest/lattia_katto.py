"""Bar-by-bar replica of pine/lattia_katto_v3.pine (long only, read-only research).

Mirrors TradingView's broker emulator: signals on bar close, market entry at the
next open, stop/limit exits checked intrabar (open->high->low->close when the
open is closer to the high, otherwise open->low->high->close).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Params:
    level_mode: str = "auto"      # auto | pivot
    auto_len: int = 50
    piv_len: int = 10
    zone_atr: float = 0.5
    use_vol: bool = True
    vol_mult: float = 1.3
    use_trend: bool = False
    ema_len: int = 200
    min_rr: float = 1.5
    cooldown: int = 10
    atr_len: int = 14
    sl_b_atr: float = 1.0
    sl_m_atr: float = 1.0
    tp_m_rr: float = 2.5
    be_rr: float = 1.0
    size_mode: str = "pct"        # pct | risk
    pct_equity: float = 10.0
    risk_pct: float = 1.0
    commission_pct: float = 0.1
    slippage_pct: float = 0.02
    initial_capital: float = 1000.0
    enable_bounce: bool = True
    enable_breakout: bool = True

    def with_(self, **kw) -> "Params":
        return replace(self, **kw)


# ── Pine-compatible indicators ─────────────────────────────────────────────
def _seeded(x: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """Pine rma/ema: seeded with the SMA of the first n valid values."""
    out = np.full(len(x), np.nan)
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) == 0 or len(x) - valid[0] < n:
        return out
    f = valid[0]
    prev = float(np.mean(x[f:f + n]))
    out[f + n - 1] = prev
    for i in range(f + n, len(x)):
        prev = alpha * x[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rma(x, n):
    return _seeded(np.asarray(x, float), n, 1.0 / n)


def ema(x, n):
    return _seeded(np.asarray(x, float), n, 2.0 / (n + 1))


def atr(h, l, c, n):
    pc = np.r_[np.nan, c[:-1]]
    tr = np.where(np.isnan(pc), h - l, np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))))
    return rma(tr, n)


def rsi(c, n):
    ch = np.r_[np.nan, np.diff(c)]
    up = rma(np.where(np.isnan(ch), np.nan, np.maximum(ch, 0)), n)
    dn = rma(np.where(np.isnan(ch), np.nan, np.maximum(-ch, 0)), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(dn == 0, 100.0, np.where(up == 0, 0.0, 100 - 100 / (1 + up / dn)))
    return np.where(np.isnan(up) | np.isnan(dn), np.nan, r)


def pivots(x: np.ndarray, L: int, high: bool) -> np.ndarray:
    """Last confirmed pivot value (Pine ta.pivothigh/low + `var` hold)."""
    s = pd.Series(x)
    win = s.rolling(2 * L + 1)
    ext = win.max() if high else win.min()
    cand = s.shift(L)
    piv = cand.where(cand == ext)
    return piv.ffill().to_numpy()


def signals(df: pd.DataFrame, p: Params) -> dict[str, np.ndarray]:
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    a = atr(h, l, c, p.atr_len)
    e = ema(c, p.ema_len)
    r = rsi(c, 14)
    vol_ma = pd.Series(v).rolling(20).mean().to_numpy()
    fast, slow = ema(c, 12), ema(c, 26)
    macd = fast - slow
    sig = ema(macd, 9)
    hist = macd - sig

    auto_ceil = pd.Series(h).rolling(p.auto_len).max().shift(1).to_numpy()
    auto_floor = pd.Series(l).rolling(p.auto_len).min().shift(1).to_numpy()
    if p.level_mode == "pivot":
        ceil_raw, floor_raw = pivots(h, p.piv_len, True), pivots(l, p.piv_len, False)
    else:
        ceil_raw, floor_raw = auto_ceil, auto_floor
    with np.errstate(invalid="ignore"):
        box_ok = ~np.isnan(ceil_raw) & ~np.isnan(floor_raw) & (ceil_raw > floor_raw)
    ceil = np.where(box_ok, ceil_raw, auto_ceil)
    floor = np.where(box_ok, floor_raw, auto_floor)
    mid = (ceil + floor) / 2
    zone = a * p.zone_atr

    with np.errstate(invalid="ignore"):
        hist_prev = np.r_[np.nan, hist[:-1]]
        mom = (hist > hist_prev) | (macd > sig)
        strong = (c > o) & ((c - o) > (h - l) * 0.5)
        has_vol = ~np.isnan(vol_ma) & (vol_ma > 0)
        vol_ok = (not p.use_vol) | ~has_vol | (v > vol_ma * p.vol_mult)
        trend_ok = np.ones(len(c), bool) if not p.use_trend else (c > e)
        c_prev, ceil_prev = np.r_[np.nan, c[:-1]], np.r_[np.nan, ceil[:-1]]
        cross = (c > ceil) & (c_prev <= ceil_prev)

        bounce_sl = np.minimum(l, floor) - a * p.sl_b_atr
        bounce_rr = (ceil - c) / np.maximum(c - bounce_sl, 1e-12)
        swept = l <= floor + zone
        reclaimed = (c > floor) & (c < mid) & strong
        bounce = swept & reclaimed & mom & trend_ok & (bounce_rr >= p.min_rr)

        break_sl = ceil - a * p.sl_m_atr
        breakout = cross & strong & vol_ok & (r > 45) & (r < 70) & mom & trend_ok

    return dict(bounce=bounce & p.enable_bounce, breakout=breakout & p.enable_breakout,
                bounce_sl=bounce_sl, break_sl=break_sl, ceil=ceil, floor=floor)


# ── Strategy emulator ──────────────────────────────────────────────────────
def run(df: pd.DataFrame, p: Params) -> tuple[list[dict], np.ndarray]:
    s = signals(df, p)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["time"].to_numpy()
    n = len(c)
    comm, slip = p.commission_pct / 100, p.slippage_pct / 100

    cash, qty = p.initial_capital, 0.0
    entry_px = entry_fee = 0.0
    entry_bar = -1
    trade_id = ""
    active_sl = active_tp = init_risk = np.nan
    be_done = False
    last_event: int | None = None
    pending_qty: float | None = None
    trades: list[dict] = []
    equity = np.empty(n)

    for t in range(n):
        closed_now = False

        # 1) orders placed on the previous close
        if pending_qty is not None:
            entry_px = o[t] * (1 + slip)
            qty = pending_qty
            entry_fee = qty * entry_px * comm
            cash -= qty * entry_px + entry_fee
            entry_bar, pending_qty = t, None

        if qty > 0:
            sl, tp = active_sl, active_tp
            px = reason = None
            if o[t] <= sl:
                px, reason = o[t] * (1 - slip), "sl"
            elif o[t] >= tp:
                px, reason = o[t], "tp"
            elif (h[t] - o[t]) < (o[t] - l[t]):          # high first
                if h[t] >= tp:
                    px, reason = tp, "tp"
                elif l[t] <= sl:
                    px, reason = sl * (1 - slip), "sl"
            else:                                         # low first
                if l[t] <= sl:
                    px, reason = sl * (1 - slip), "sl"
                elif h[t] >= tp:
                    px, reason = tp, "tp"
            if px is not None:
                proceeds = qty * px
                fee = proceeds * comm
                cash += proceeds - fee
                cost = qty * entry_px + entry_fee
                pnl = proceeds - fee - cost
                if reason == "sl" and be_done:
                    reason = "be"
                trades.append(dict(
                    type=trade_id, entry_time=int(ts[entry_bar]), exit_time=int(ts[t]),
                    entry=entry_px, exit=px, reason=reason, bars=t - entry_bar,
                    pnl=pnl, ret_pct=pnl / cost * 100, r=pnl / (qty * init_risk)))
                qty, closed_now = 0.0, True

        # 2) script logic on this bar's close
        if closed_now:
            last_event = t
            active_sl = active_tp = init_risk = np.nan

        flat = qty == 0
        cd_ok = last_event is None or t - last_event >= p.cooldown
        if flat and cd_ok and t < n - 1:
            new = None
            if s["bounce"][t]:
                new, sl, tp = "Pomppu", s["bounce_sl"][t], s["ceil"][t]
            elif s["breakout"][t]:
                sl = s["break_sl"][t]
                new, tp = "Murto", c[t] + (c[t] - sl) * p.tp_m_rr
            if new:
                eq = cash
                if p.size_mode == "risk":
                    q = eq * p.risk_pct / 100 / (c[t] - sl)
                    q = min(q, eq / c[t])
                else:
                    q = eq * p.pct_equity / 100 / c[t]
                trade_id, active_sl, active_tp = new, sl, tp
                init_risk, be_done, last_event = c[t] - sl, False, t
                pending_qty = q

        if qty > 0 and p.be_rr > 0 and not be_done and not np.isnan(init_risk):
            if h[t] >= entry_px + init_risk * p.be_rr:
                active_sl = max(active_sl, entry_px)
                be_done = True

        equity[t] = cash + qty * c[t]

    return trades, equity


# ── Metrics ────────────────────────────────────────────────────────────────
def r_stats(trades: list[dict]) -> dict:
    if not trades:
        return dict(trades=0, win_pct=None, pf=None, avg_r=None, total_r=0.0, t_stat=None)
    r = np.array([x["r"] for x in trades])
    pos, neg = r[r > 0].sum(), -r[r < 0].sum()
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return dict(trades=len(r), win_pct=float((r > 0).mean() * 100),
                pf=float(pos / neg) if neg > 0 else None,
                avg_r=float(r.mean()), total_r=float(r.sum()),
                t_stat=float(r.mean() / (sd / np.sqrt(len(r)))) if sd > 0 else None)


def metrics(df: pd.DataFrame, trades: list[dict], equity: np.ndarray, p: Params) -> dict:
    c = df["close"].to_numpy(float)
    years = (df["time"].iloc[-1] - df["time"].iloc[0]) / (365.25 * 86400 * 1000)
    peak = np.maximum.accumulate(equity)
    dd = float(((equity - peak) / peak).min() * 100)
    ret = float(equity[-1] / p.initial_capital - 1) * 100
    cagr = float(((equity[-1] / p.initial_capital) ** (1 / years) - 1) * 100) if years > 0.25 and equity[-1] > 0 else None
    held = sum(x["bars"] + 1 for x in trades)
    out = dict(r_stats(trades),
               ret_pct=ret, cagr_pct=cagr, max_dd_pct=dd,
               bh_pct=float(c[-1] / c[0] - 1) * 100,
               exposure_pct=held / len(c) * 100,
               years=float(years),
               exits={k: sum(1 for x in trades if x["reason"] == k) for k in ("tp", "sl", "be")})
    for typ in ("Pomppu", "Murto"):
        out[typ] = r_stats([x for x in trades if x["type"] == typ])
    return out
