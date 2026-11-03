import unittest
from research.odds_api_ingest import normalize, SPORT_KEYS

class OddsIngestTests(unittest.TestCase):
    def provider(self):
        event={"id":"game-1","commence_time":"2025-11-10T20:00:00Z",
               "home_team":"Home College","away_team":"Away College",
               "bookmakers":[{"key":"sample_book","last_update":"2025-11-10T18:00:00Z",
                 "markets":[
                   {"key":"spreads","last_update":"2025-11-10T18:00:00Z",
                    "outcomes":[{"name":"Home College","point":-3.5,"price":-110},
                                {"name":"Away College","point":3.5,"price":-110}]},
                   {"key":"totals","last_update":"2025-11-10T18:00:00Z",
                    "outcomes":[{"name":"Over","point":145.5,"price":-105},
                                {"name":"Under","point":145.5,"price":-115}]},
                   {"key":"h2h","last_update":"2025-11-10T18:00:00Z",
                    "outcomes":[{"name":"Home College","price":-150},
                                {"name":"Away College","price":130}]}
                 ]}]}
        return {"timestamp":"2025-11-10T19:00:00Z","data":[event]}

    def test_all_three_sports_and_markets(self):
        for sport in SPORT_KEYS:
            rows,errors=normalize(self.provider(),sport)
            self.assertEqual(len(rows),6)
            self.assertEqual(errors,[])
            self.assertEqual(set(r["market"] for r in rows),
                             {"spread","total","moneyline"})
            self.assertTrue(all(r["book"]==r["opposing_book"] for r in rows))
            self.assertTrue(all(r["quote_time_utc"]==r["opposing_quote_time_utc"] for r in rows))
            sides=[r for r in rows if r["market"]=="spread"]
            self.assertEqual(sorted(r["line"] for r in sides),[-3.5,3.5])

    def test_no_postgame_or_post_snapshot_quotes(self):
        x=self.provider()
        x["timestamp"]="2025-11-10T21:00:00Z"
        rows,_=normalize(x,"NFL")
        self.assertEqual(rows,[])
        x=self.provider()
        x["data"][0]["bookmakers"][0]["markets"][0]["last_update"]="2025-11-10T19:30:00Z"
        rows,errors=normalize(x,"NFL")
        self.assertEqual(len(rows),4)
        self.assertTrue(errors)

    def test_rejects_misaligned_spreads(self):
        x=self.provider()
        x["data"][0]["bookmakers"][0]["markets"][0]["outcomes"][1]["point"]=4.5
        rows,_=normalize(x,"NCAAF")
        self.assertFalse(any(r["market"]=="spread" for r in rows))
        self.assertEqual(len(rows),4)

    def test_only_halfpoint_or_integer_lines(self):
        x=self.provider()
        x["data"][0]["bookmakers"][0]["markets"][1]["outcomes"][0]["point"]=145.25
        x["data"][0]["bookmakers"][0]["markets"][1]["outcomes"][1]["point"]=145.25
        rows,_=normalize(x,"NCAAB")
        self.assertFalse(any(r["market"]=="total" for r in rows))

if __name__=="__main__":unittest.main()
