import unittest
import numpy as np
import pandas as pd
from models.train_ncaab import pregame_features, discrete_three_way, evaluate

class TestNCAAB(unittest.TestCase):
    def test_spread_and_total_direction_and_push(self):
        for mean, threshold, expectation in [
            (4,3,[1,0,0]), (3,3,[0,1,0]), (2,3,[0,0,1]),
            (145,145.5,[0,0,1]),(146,145.5,[1,0,0])]:
            d=discrete_three_way(np.array([float(mean)]),
                                 np.array([0.]),np.array([float(threshold)]))
            np.testing.assert_allclose(d[0],expectation)

    def test_same_day_cannot_observe_final(self):
        d=pd.DataFrame([
            dict(date="2024-11-03",season=2024,home="A",away="B",home_score=110,away_score=55),
            dict(date="2024-11-03",season=2024,home="A",away="C",home_score=40,away_score=30),
            dict(date="2024-11-04",season=2024,home="A",away="D",home_score=60,away_score=61)])
        d["date"]=pd.to_datetime(d.date,utc=True)
        f=pregame_features(d)
        np.testing.assert_allclose(f[0,[0,1,5]],f[1,[0,1,5]])
        self.assertNotEqual(f[1,0],f[2,0])

    def test_season_transition_regresses_team_priors(self):
        d=pd.DataFrame([
            dict(date="2024-12-01",season=2024,home="A",away="B",home_score=150,away_score=40),
            dict(date="2024-12-02",season=2024,home="A",away="C",home_score=110,away_score=60),
            dict(date="2025-12-01",season=2025,home="A",away="D",home_score=70,away_score=69)])
        d["date"]=pd.to_datetime(d.date,utc=True)
        f=pregame_features(d)
        self.assertEqual(f[0,0],70.)
        self.assertEqual(f[2,5],0.)
        self.assertGreater(f[2,0],70.)
        self.assertLess(f[2,0],f[1,0])

    def test_missing_historical_seasons_fail_closed(self):
        d=pd.DataFrame([
            dict(date=pd.Timestamp("2025-01-01",tz="UTC"),season=2025,
                 home="A",away="B",home_score=72,away_score=70)])
        with self.assertRaises(RuntimeError):
            evaluate(d)

if __name__=="__main__":
    unittest.main()
