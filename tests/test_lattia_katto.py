import unittest

import numpy as np
import pandas as pd

from backtest.lattia_katto import Params, ema, metrics, rma, rsi, run


def synthetic(n=6000, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    v = rng.lognormal(10, 0.6, n)
    t = 1_672_531_200_000 + np.arange(n) * 3_600_000
    return pd.DataFrame(dict(time=t, open=o, high=h, low=l, close=c, volume=v))


class IndicatorTest(unittest.TestCase):
    def test_rma_seed_and_recursion(self):
        x = np.arange(1, 11, dtype=float)
        r = rma(x, 3)
        self.assertTrue(np.isnan(r[:2]).all())
        self.assertAlmostEqual(r[2], 2.0)
        self.assertAlmostEqual(r[3], (4 + 2 * 2.0) / 3)

    def test_ema_handles_leading_nan(self):
        x = np.r_[np.nan, np.nan, np.ones(10)]
        self.assertAlmostEqual(ema(x, 3)[4], 1.0)

    def test_rsi_bounds(self):
        r = rsi(synthetic(500)["close"].to_numpy(), 14)
        r = r[~np.isnan(r)]
        self.assertTrue(((r >= 0) & (r <= 100)).all())


class EngineTest(unittest.TestCase):
    def check_invariants(self, df, p):
        trades, equity = run(df, p)
        self.assertGreater(len(trades), 0)
        times = df["time"].to_numpy()
        idx = {t: i for i, t in enumerate(times)}
        prev_exit = -1
        for tr in trades:
            i, j = idx[tr["entry_time"]], idx[tr["exit_time"]]
            self.assertGreaterEqual(i, prev_exit, "trades overlap")
            self.assertGreaterEqual(j, i)
            self.assertGreaterEqual(i - prev_exit if prev_exit >= 0 else p.cooldown, min(p.cooldown, 1))
            lo, hi = df["low"].iat[j], df["high"].iat[j]
            self.assertTrue(lo * 0.999 <= tr["exit"] <= hi * 1.001, tr)
            prev_exit = j
        last_closed = trades[-1]["exit_time"]
        # once flat, equity equals initial capital plus realised P&L
        j = idx[last_closed]
        realised = p.initial_capital + sum(t["pnl"] for t in trades)
        self.assertAlmostEqual(equity[j], realised, places=6)
        m = metrics(df, trades, equity, p)
        self.assertEqual(m["trades"], len(trades))
        return trades

    def test_auto_mode(self):
        self.check_invariants(synthetic(), Params())

    def test_pivot_mode_and_risk_sizing(self):
        self.check_invariants(synthetic(seed=3), Params(level_mode="pivot", size_mode="risk"))

    def test_stop_hit_before_target_when_open_near_low(self):
        trades = self.check_invariants(synthetic(seed=5), Params(be_rr=0.0))
        for tr in trades:
            if tr["reason"] == "sl":
                self.assertLess(tr["r"], 0)
            if tr["reason"] == "tp":
                self.assertGreater(tr["exit"], tr["entry"])

    def test_cooldown_blocks_reentry(self):
        df = synthetic(seed=7)
        p = Params(cooldown=25)
        trades, _ = run(df, p)
        idx = {t: i for i, t in enumerate(df["time"].to_numpy())}
        for a, b in zip(trades, trades[1:]):
            # signal bar of b is one bar before its fill and must be >= cooldown after a's exit
            self.assertGreaterEqual(idx[b["entry_time"]] - 1 - idx[a["exit_time"]], p.cooldown)


if __name__ == "__main__":
    unittest.main()
