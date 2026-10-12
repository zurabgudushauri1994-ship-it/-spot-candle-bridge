import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("kronos_bridge", Path(__file__).parents[1] / "kronos/run.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class KronosInputs(unittest.TestCase):
    def setUp(self):
        self.step = 15 * 60000
        self.now = 1791800100000 // self.step * self.step + 10000
        end = self.now // self.step * self.step
        self.rows = [[end-(200-i)*self.step, "100", "102", "99", "101", "10"] for i in range(200)]

    def test_valid_closed_frame(self):
        df, stamps = bridge.validate_frame(self.rows, "15m", self.now, self.now)
        self.assertEqual(len(df), 200)
        self.assertEqual(df.volume.iloc[-1], 10)

    def test_rejects_future_and_stale_candles(self):
        with self.assertRaises(ValueError):
            bridge.validate_frame(self.rows, "15m", self.now, self.now + 3*self.step)
        future = [r.copy() for r in self.rows]
        for r in future:
            r[0] += self.step
        with self.assertRaises(ValueError):
            bridge.validate_frame(future, "15m", self.now, self.now)

    def test_rejects_gap_and_invalid_price(self):
        bad = [r.copy() for r in self.rows]
        bad[-1][0] += self.step
        with self.assertRaises(ValueError):
            bridge.validate_frame(bad, "15m", self.now, self.now)
        bad = [r.copy() for r in self.rows]
        bad[-1][2] = "98"
        with self.assertRaises(ValueError):
            bridge.validate_frame(bad, "15m", self.now, self.now)

    def test_flat_prices_have_neutral_rsi_and_no_breakout(self):
        df, _ = bridge.validate_frame(self.rows, "15m", self.now, self.now)
        values = bridge.technical(df)
        self.assertEqual(values["rsi14"], 50)
        self.assertFalse(values["breakout_previous20"])
        self.assertEqual(values["trend"], "mixed")


if __name__ == "__main__":
    unittest.main()
