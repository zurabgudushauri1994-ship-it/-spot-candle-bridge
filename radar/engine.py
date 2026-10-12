"""Deterministic signal rules.  Every input row must already be a closed candle."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import numpy as np
import pandas as pd


REQUIRED = ("open_time_ms", "open", "high", "low", "close", "base_volume")


def frame(rows: list[list[object]] | pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Return validated, sorted closed OHLCV.  No timestamp is invented."""
    df = pd.DataFrame(rows, columns=REQUIRED) if not isinstance(rows, pd.DataFrame) else rows.copy()
    if any(c not in df for c in REQUIRED) or len(df) < 60:
        raise ValueError("insufficient OHLCV")
    df = df.loc[:, REQUIRED].astype(float).sort_values("open_time_ms").reset_index(drop=True)
    step = minutes * 60_000
    if not np.isfinite(df.to_numpy()).all() or not (df.open_time_ms.diff().iloc[1:] == step).all():
        raise ValueError("nonfinite or gapped OHLCV")
    if not ((df.low > 0) & (df.low <= df[["open", "close"]].min(axis=1)) & (df.high >= df[["open", "close"]].max(axis=1)) & (df.base_volume >= 0)).all():
        raise ValueError("invalid OHLCV")
    return df


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["ema20"] = x.close.ewm(span=20, adjust=False).mean()
    x["ema50"] = x.close.ewm(span=50, adjust=False).mean()
    d = x.close.diff()
    gain, loss = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    x["rsi14"] = np.where(loss == 0, 100.0, 100 - 100 / (1 + gain / loss))
    tr = pd.concat([x.high - x.low, (x.high - x.close.shift()).abs(), (x.low - x.close.shift()).abs()], axis=1).max(axis=1)
    x["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    macd = x.close.ewm(span=12, adjust=False).mean() - x.close.ewm(span=26, adjust=False).mean()
    x["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    x["relative_volume"] = x.base_volume / x.base_volume.shift(1).rolling(20).mean()
    x["range20"] = (x.high.rolling(20).max() - x.low.rolling(20).min()) / x.close
    x["range20_prev"] = x["range20"].shift(5)
    return x


@dataclass(frozen=True)
class Signal:
    state: str
    score: int
    reasons: list[str]
    entry: float | None
    stop: float | None
    tp1: float | None
    tp2: float | None
    reward_risk: float | None
    support: float
    resistance: float
    stale: bool = False

    def json(self) -> dict:
        return asdict(self)


def _empty(state: str, support: float, resistance: float, *reasons: str) -> Signal:
    return Signal(state, 0, list(reasons), None, None, None, None, None, support, resistance)


def early_momentum(df: pd.DataFrame, btc_returns: pd.Series | None = None, fee_bps: float = 12.0) -> Signal:
    """Use only the final row and preceding rows; never uses future prices."""
    x = indicators(df)
    if len(x) < 60:
        raise ValueError("need 60 candles")
    q = x.iloc[-1]
    prev = x.iloc[:-1]
    support, resistance = float(prev.low.iloc[-20:].min()), float(prev.high.iloc[-20:].max())
    atr = float(q.atr14)
    if not math.isfinite(atr) or atr <= 0:
        return _empty("AVOID", support, resistance, "ATR puuttuu")
    close = float(q.close)
    score, reasons = 0, []
    # Structure: both a higher local low and a higher local high versus prior 15-candle windows.
    local_low, old_low = float(x.low.iloc[-5:].min()), float(x.low.iloc[-20:-5].min())
    local_high, old_high = float(x.high.iloc[-5:].max()), float(x.high.iloc[-20:-5].max())
    structure = local_low > old_low and local_high >= old_high
    if structure: score += 18; reasons.append("15m higher low / higher high")
    reclaim = close > q.ema20 and x.close.iloc[-2] <= x.ema20.iloc[-2]
    alignment = close > q.ema20 and q.ema20 > q.ema50
    if reclaim: score += 16; reasons.append("EMA20 takaisinvaltaus")
    elif alignment: score += 10; reasons.append("EMA20 yli EMA50")
    compression = bool(q.range20 < q.range20_prev * .82) if math.isfinite(q.range20_prev) else False
    if compression: score += 8; reasons.append("sivuttaisliike kiristyy")
    if q.relative_volume >= 1.35: score += 16; reasons.append(f"suhteellinen volyymi {q.relative_volume:.1f}x")
    elif q.relative_volume >= 1.05: score += 6; reasons.append("volyymi vahvistuu")
    rsi_turn = 45 <= q.rsi14 <= 66 and q.rsi14 > x.rsi14.iloc[-4]
    if rsi_turn: score += 10; reasons.append("RSI nousee ilman yliostoa")
    if q.macd_hist > x.macd_hist.iloc[-3] and q.macd_hist > x.macd_hist.iloc[-2]: score += 8; reasons.append("MACD-histogrammi paranee")
    retest = abs(float(q.low) - float(q.ema20)) <= atr * .45 and close > q.ema20
    if retest: score += 10; reasons.append("EMA20-tuki testattu")
    if btc_returns is not None and len(btc_returns) >= 4:
        rel = x.close.pct_change(4).iloc[-1] - btc_returns.iloc[-1]
        if rel > .003: score += 8; reasons.append("vahvempi kuin BTC")
    extension = (close - q.ema20) / atr
    liquidity_bad = q.base_volume * close <= 15_000
    near_resistance = (resistance - close) / atr < .75
    if extension > 2.4 or q.rsi14 >= 75:
        return Signal("TOO_LATE / AVOID", max(0, score - 20), reasons + ["nousu on venynyt"], None, None, None, None, None, support, resistance)
    if liquidity_bad:
        return Signal("TOO_LATE / AVOID", max(0, score - 18), reasons + ["15m likviditeetti liian heikko"], None, None, None, None, None, support, resistance)
    entry = close
    stop = min(float(q.low) - .2 * atr, support - .1 * atr)
    risk = entry - stop
    tp1 = min(resistance, entry + 1.5 * risk)
    tp2 = entry + 2.5 * risk
    rr = (tp2 - entry) / risk if risk > 0 else 0.0
    if score >= 62 and not near_resistance and rr >= 1.8:
        state = "BUY_CONFIRMED"
    elif score >= 46 and rr >= 1.5:
        state = "ENTRY_NEAR"
    elif score >= 28:
        state = "EARLY_WATCH"
    else:
        state = "TOO_LATE / AVOID"
    if near_resistance and state == "BUY_CONFIRMED":
        state = "ENTRY_NEAR"; reasons.append("vastus lähellä")
    # Fees are reported in backtest; include them in the feasibility check.
    if rr <= (fee_bps / 10_000) * 2:
        state = "TOO_LATE / AVOID"; reasons.append("kulujen jälkeen liian pieni tuotto-odotus")
    return Signal(state, min(100, score), reasons, entry if state != "TOO_LATE / AVOID" else None, stop if state != "TOO_LATE / AVOID" else None, tp1 if state != "TOO_LATE / AVOID" else None, tp2 if state != "TOO_LATE / AVOID" else None, float(rr) if risk > 0 else None, support, resistance)
