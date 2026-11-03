import unittest
import numpy as np
import pandas as pd
from models.train_football import build_causal_features, three_way_from_residuals, train

class TestFootball(unittest.TestCase):
    def test_margin_direction_and_integer_push(self):
        d = three_way_from_residuals(
            np.array([4., -4.]), np.array([0.]), np.array([3., -3.]))
        np.testing.assert_allclose(d[0], [1, 0, 0])
        np.testing.assert_allclose(d[1], [0, 0, 1])
        d = three_way_from_residuals(np.array([3.]), np.array([0.]), np.array([3.]))
        np.testing.assert_allclose(d[0], [0, 1, 0])
        # Half-point spreads can never push when modeled scores are integers.
        d = three_way_from_residuals(np.array([3.]), np.array([0.]), np.array([3.5]))
        np.testing.assert_allclose(d[0], [0, 0, 1])

    def test_same_date_features_cannot_see_earlier_final(self):
        rows = [
            dict(date="2025-09-01",season=2025,home_team="A",away_team="B",
                 home_points=80,away_points=0),
            dict(date="2025-09-01",season=2025,home_team="A",away_team="C",
                 home_points=0,away_points=20),
            dict(date="2025-09-02",season=2025,home_team="A",away_team="D",
                 home_points=10,away_points=20)]
        d=pd.DataFrame(rows)
        d["date"]=pd.to_datetime(d.date,utc=True)
        feat=build_causal_features(d)
        self.assertEqual(feat[0,0],feat[1,0])
        self.assertNotEqual(feat[1,0],feat[2,0])

    def test_train_rejects_insufficient_history(self):
        d=pd.DataFrame([dict(date=pd.Timestamp("2025-09-01",tz="UTC"),season=2025,
                             home_team="A",away_team="B",home_points=4,away_points=2)])
        with self.assertRaises(ValueError):
            train("NFL",d)

if __name__ == "__main__":
    unittest.main()
