import json
import tempfile
import unittest
from pathlib import Path
from models.market_engine import Quote, Distribution, breakeven, payout, qualify, three_way_ev
from models.run_pregame import run

def quote(**kw):
    base = dict(event_id="sample-event", event_start_utc="2026-11-04T00:00:00Z",
                observed_utc="2026-11-03T18:00:00Z", book="TEST ONLY",
                sport="NCAAB", market="spread", selection="Away +3", line="+3",
                american_odds=-110, executable_verified=False)
    base.update(kw)
    return Quote(**base)

class TestMarketEngine(unittest.TestCase):
    def test_exact_odds(self):
        self.assertAlmostEqual(breakeven(-110), 110 / 210)
        self.assertAlmostEqual(breakeven(145), 100 / 245)
        self.assertAlmostEqual(payout(-110), 100/110)

    def test_push_refund_and_ev(self):
        dist = Distribution(.55, .10, .35, "2026-11-03T17:00:00Z", "test", "fixture")
        self.assertAlmostEqual(three_way_ev(dist, -110), .55 * 100/110 - .35)

    def test_no_model_fails_closed(self):
        row = qualify(quote(), None, None, 7705.48)
        self.assertEqual(row["state"], "CANDIDATE")
        self.assertEqual(row["approved_risk_usd"], 0)
        self.assertEqual(row["model_probability"], "NOT_COMPUTED")

    def test_missing_release_fails_closed_even_good_model(self):
        dist = Distribution(.65, 0.0, .35, "2026-11-03T17:00:00Z", "test", "fixture")
        row = qualify(quote(executable_verified=True), dist, None, 7705.48)
        self.assertEqual(row["approved_risk_usd"], 0)
        self.assertIn("No matching model release manifest", row["blockers"])

    def test_rejects_invalid_probability_or_postgame_quote(self):
        bad = Distribution(.8, .4, .1, "2026-11-03T17:00:00Z", "test", "fixture")
        with self.assertRaises(ValueError):
            qualify(quote(), bad, None, 1000)
        with self.assertRaises(ValueError):
            qualify(quote(observed_utc="2026-11-04T00:00:00Z"), None, None, 1000)

    def test_append_only_deduplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/"input.json"
            dest = Path(folder)/"registry.jsonl"
            source.write_text(json.dumps({"bankroll": 7705.48, "quotes": [
                dict(event_id="e1", event_start_utc="2026-11-04T00:00:00Z",
                     observed_utc="2026-11-03T18:00:00Z", book="TEST ONLY",
                     sport="NCAAB", market="spread", selection="Away", line="+3",
                     american_odds=-110, executable_verified=False)]}))
            self.assertEqual(run(source,dest)["new_snapshots"],1)
            before=dest.read_bytes()
            self.assertEqual(run(source,dest)["new_snapshots"],0)
            self.assertEqual(dest.read_bytes(), before)
            row=json.loads(dest.read_text().strip())
            self.assertFalse(row["official_placed"])
            self.assertEqual(row["approved_risk_usd"],0)

if __name__ == "__main__":
    unittest.main()
