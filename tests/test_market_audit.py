import json
import tempfile
import unittest
from pathlib import Path

from research.market_audit import (audit,checked,settlement,metrics,bootstrap_ci,
                                   implied,odds_profit)

def fixture(sport="NFL",market="spread",selection="home",line=-3.5,
            home_score=27,away_score=20):
    return dict(event_id="E-1",season=2025,sport=sport,market=market,
                selection=selection,line=line,american_odds=-110,
                opposing_american_odds=-110, book="HISTORICAL_BOOK",
                quote_time_utc="2025-10-21T16:00:00Z",
                forecast_time_utc="2025-10-21T15:00:00Z",
                start_time_utc="2025-10-21T20:00:00Z",
                home_score=home_score,away_score=away_score,
                p_win=.6,p_push=0.,p_loss=.4,
                scope="full_game_including_overtime",model_version="TEST-ONLY",
                model_provenance_sha256="a"*64,quote_provenance_sha256="b"*64,
                source_url="https://example.test/model",
                quote_source_url="https://example.test/quote",
                market_pair_verified=True)

class MarketAuditTests(unittest.TestCase):
    def test_settlement_selected_side_spread_orientation(self):
        x=fixture()
        self.assertEqual(settlement(x),1)
        x["selection"]="away";x["line"]=+3.5
        self.assertEqual(settlement(x),-1)
        x["line"]=+7.
        self.assertEqual(settlement(x),0)
        x["line"]=+7.5
        self.assertEqual(settlement(x),1)

    def test_total_and_moneyline(self):
        x=fixture(market="total",selection="under",line=47.5)
        self.assertEqual(settlement(x),1)
        x["selection"]="over"
        self.assertEqual(settlement(x),-1)
        x=fixture(market="moneyline",selection="home",line="",home_score=20,away_score=20)
        self.assertEqual(settlement(x),0)

    def test_basketball_and_fbs(self):
        for sport in ("NCAAF","NCAAB"):
            r=checked(fixture(sport=sport))
            self.assertEqual(r["outcome"],1)
            self.assertTrue(r["hypothetical_selected"])
            self.assertGreater(r["model_expected_roi"],0)

    def test_precise_break_even_and_novig(self):
        self.assertAlmostEqual(implied(-110),110/210)
        self.assertAlmostEqual(odds_profit(120),1.2)
        x=checked(fixture())
        self.assertAlmostEqual(x["no_vig_conditional_win"],.5)

    def test_fails_closed_on_incomplete_provenance_and_future_quote(self):
        r=fixture();r["quote_time_utc"]=r["start_time_utc"]
        with self.assertRaises(ValueError):
            checked(r)
        r=fixture();r["market_pair_verified"]=False
        with self.assertRaises(ValueError):
            checked(r)
        r=fixture();del r["quote_provenance_sha256"]
        with self.assertRaises(ValueError):
            checked(r)

    def test_integer_line_push_and_conditional_probability(self):
        r=fixture(line=-7.);r.update(p_win=.5,p_push=.1,p_loss=.4)
        parsed=checked(r)
        self.assertEqual(parsed["outcome"],0)
        self.assertAlmostEqual(parsed["model_conditional_win"],.5/.9)
        self.assertAlmostEqual(parsed["model_expected_roi"],.5*100/110-.4)

    def test_no_retroactive_bet_or_persistence_without_data(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"private.jsonl"
            p.write_text("",encoding="utf-8")
            r=audit(p)
            self.assertEqual(r["approved_live_risk_usd"],0)
            self.assertEqual(r["official_wagers_changed"],0)
            for sport in ("NFL","NCAAF","NCAAB"):
                self.assertEqual(r["sports"][sport]["coverage"]["unique_events"],0)
                self.assertFalse(r["sports"][sport]["production_approved"])

    def test_dedup_and_per_sport_reporting(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"data.jsonl"
            rows=[fixture("NFL"), fixture("NCAAF"), fixture("NCAAB")]
            for i,row in enumerate(rows):row["event_id"]="E"+str(i)
            p.write_text("\n".join(json.dumps(r) for r in rows)+"\n")
            result=audit(p)
            self.assertEqual(result["accepted"],3)
            self.assertEqual(result["rejected"],0)
            self.assertEqual(result["sports"]["NCAAB"]["coverage"]["unique_events"],1)
            self.assertIsNotNone(result["sports"]["NCAAF"]["cluster_ci"])
            p.write_text(p.read_text()+json.dumps(rows[0])+"\n")
            result=audit(p)
            self.assertEqual(result["accepted"],3)
            self.assertEqual(result["rejected"],1)

if __name__=="__main__":unittest.main()
