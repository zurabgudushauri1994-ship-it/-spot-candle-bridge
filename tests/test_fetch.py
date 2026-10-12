import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fetch_candles import closed_rows

class CandleTests(unittest.TestCase):
    def test_excludes_partial_candle(self):
        now = 1_800_000
        rows = [[0, '1','3','0.5','2','10'],[900_000,'2','5','1','4','20'],[1_800_000,'4','6','3','5','30']]
        self.assertEqual(closed_rows(rows, 15, now + 5_000), [[0, '1','3','0.5','2','10'],[900_000,'2','5','1','4','20']])
    def test_dedupe_sort(self):
        rows=[[1_800_000,'2','3','1','2','4'],[0,'1','2','0','1','2'],[0,'1','2','0','1','2']]
        self.assertEqual([r[0] for r in closed_rows(rows,15,3_600_000)], [0,1_800_000])

if __name__=='__main__': unittest.main()
