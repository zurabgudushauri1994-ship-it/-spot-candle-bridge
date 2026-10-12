import unittest
from radar.engine import frame, early_momentum
from radar.backtest import test_pair

def rows(n=100):
    out=[]
    for i in range(n):
        c=100+i*.02
        out.append([i*900000, c-.1, c+.2, c-.2, c, 100])
    return out

class RadarTests(unittest.TestCase):
    def test_rejects_gap(self):
        x=rows();x[50][0]+=1
        with self.assertRaises(ValueError): frame(x,15)
    def test_signal_never_uses_future(self):
        x=rows(); before=early_momentum(frame(x,15)); x[-1][4]=200
        self.assertEqual(before,early_momentum(frame(rows(),15)))
    def test_backtest_has_costs_and_oos(self):
        r=test_pair(rows(150))
        self.assertIn("out_of_sample",r);self.assertEqual(r["automatic_trading"],False)
if __name__ == "__main__": unittest.main()
