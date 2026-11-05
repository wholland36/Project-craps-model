import json,hashlib,tempfile,unittest
from pathlib import Path
from research.ea_ratings import rating_gap,scale_reports,load_roster,normalize


def player(pid='1',rating=95,team='72',group='QB',iteration='week8'):
    return dict(ea_player_id=pid,overall_rating=rating,ea_team_id=team,position_group=group,iteration=iteration)


class RatingTests(unittest.TestCase):
    def test_rating_gap_not_scoring_points(self):
        r=rating_gap(player(),player('2',75),.5)
        self.assertEqual(r['overall_rating_gap'],20);self.assertEqual(r['snap_weighted_rating_loss'],10)
        self.assertEqual(r['normalized_rating_loss'],.1);self.assertIsNone(r['expected_points_over_replacement'])
    def test_better_rated_backup_preserves_signed_gap(self):
        r=rating_gap(player(rating=80),player('2',90))
        self.assertEqual(r['overall_rating_gap'],-10);self.assertEqual(r['normalized_rating_loss'],0)
    def test_already_embedded_absence_can_have_zero_new_loss(self):
        self.assertEqual(rating_gap(player(),player('2',60),0)['normalized_rating_loss'],0)
    def test_same_player_rejected(self):
        with self.assertRaises(ValueError):rating_gap(player(),player())
    def test_cross_team_replacement_rejected(self):
        with self.assertRaises(ValueError):rating_gap(player(),player('2',team='other'))
    def test_different_role_rejected(self):
        with self.assertRaises(ValueError):rating_gap(player(),player('2',group='WR'))
    def test_mixed_iteration_rejected(self):
        with self.assertRaises(ValueError):rating_gap(player(),player('2',iteration='week7'))
    def test_invalid_exposure_rejected(self):
        for x in [True,-.1,1.1,float('nan')]:
            with self.assertRaises(ValueError):rating_gap(player(),player('2'),x)
    def test_invalid_rating_rejected(self):
        with self.assertRaises(ValueError):rating_gap(player(rating=100),player('2'))
    def manifest(self):
        return dict(captured_at='2026-11-05T12:00:00+00:00',players_sha256='a'*64,iteration='week8')
    def report(self):
        return dict(ea_identity_verified=True,ea_player_id='1',ea_replacement_player_id='2',ea_team_id='72',expected_lost_snap_share=1.)
    def test_future_rating_snapshot_cannot_backfill(self):
        with self.assertRaises(ValueError):scale_reports([self.report()],[player(),player('2',70)],self.manifest(),'2025-11-05T12:00:00+00:00')
    def test_missing_replacement_not_imputed(self):
        r=scale_reports([self.report()],[player()],self.manifest(),'2026-11-05T13:00:00+00:00')
        self.assertTrue(r['missing_inputs']);self.assertEqual(r['rating_loss_features'],[])
    def test_injury_identity_crosswalk_required(self):
        r=self.report();r['ea_identity_verified']=False
        self.assertTrue(scale_reports([r],[player(),player('2')],self.manifest(),'2026-11-05T13:00:00+00:00')['missing_inputs'])
    def test_scaling_outputs_remain_research(self):
        r=scale_reports([self.report()],[player(),player('2',70)],self.manifest(),'2026-11-05T13:00:00+00:00')
        self.assertFalse(r['production_approved']);self.assertIsNone(r['scoring_point_adjustment'])
        self.assertEqual(r['rating_loss_features'][0]['overall_rating_gap'],25)
    def test_roster_hash_and_coverage_guard(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);raw=json.dumps([player(),player('2')]).encode();(p/'players.json').write_bytes(raw)
            m=self.manifest();m.update(players_sha256=hashlib.sha256(raw).hexdigest(),downloaded_unique_players=2)
            (p/'manifest.json').write_text(json.dumps(m));self.assertEqual(len(load_roster(p)[0]),2)
            (p/'players.json').write_bytes(raw+b' ')
            with self.assertRaises(ValueError):load_roster(p)
