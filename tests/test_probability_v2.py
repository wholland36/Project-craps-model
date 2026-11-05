import math
import pytest
from research.probability_v2 import (jointly_center,center_audit,proper_scores,same_book_novig,
 expected_roi,event_balanced,week_block_ci,offered_line_push_diagnostic,fixed_policy_roi)


def test_joint_center_preserves_paired_support_and_covariance():
    p=(2,50);r=[(4,2),(0,-4),(2,8)]
    c=jointly_center(p,r,fitted_through='2025-01-01T00:00:00Z',forecast_cutoff='2026-01-01T00:00:00Z')
    for before,after in zip(r,c['residual_pairs']):
        assert [p[j]+before[j] for j in range(2)]==pytest.approx([c['point'][j]+after[j] for j in range(2)])
    assert [sum(x[j] for x in c['residual_pairs']) for j in range(2)]==pytest.approx([0,0])


def test_center_rejects_leakage_and_stacking():
    for kwargs in ({'fitted_through':'2026-02-01T00:00:00Z'}, {'bias_already_applied':True}):
        k=dict(fitted_through='2025-01-01T00:00:00Z',forecast_cutoff='2026-01-01T00:00:00Z');k.update(kwargs)
        with pytest.raises(ValueError):jointly_center((0,40),[(0,0)],**k)


def test_center_audit_separates_discretization():
    a=center_audit((1,40),[(2,0),(0,0)],[(21,19),(22,19)])
    assert a['continuous_distribution_mean']==[2,40]
    assert a['discretization_shift']==[.5,.5]


def test_proper_scores_push_conditioning_and_perfect():
    s=proper_scores((.4,.2,.4),0)
    assert s['conditional_brier'] is None
    assert s['threeway_brier']==pytest.approx(.96)
    assert proper_scores((1,0,0),1)['threeway_logloss']==0
    assert math.isinf(proper_scores((0,0,1),1)['threeway_logloss'])
    assert proper_scores((.4,.2,.4),1)['conditional_win']==.5
    with pytest.raises(ValueError):proper_scores((.4,.4,.4),1)


def pair():
    a=dict(event_id='a',book='x',market='spread',scope='full_game_including_overtime',quote_time_utc='2026-01-01T00:00:00Z',start_time_utc='2026-01-02T00:00:00Z',selection='home',line=-3,american_odds=-110)
    return a,dict(a,selection='away',line=3)


def test_novig_pair_rejects_crossbook_line_time_and_future():
    a,b=pair();assert same_book_novig(a,b)==.5
    for change in ({'book':'y'},{'line':3.5},{'quote_time_utc':'2026-01-03T00:00:00Z'},{'selection':'home'}):
        with pytest.raises(ValueError):same_book_novig(a,dict(b,**change))


def test_ev_push_refund_distinct_from_conditional_probability():
    assert expected_roi((.4,.2,.4),100)==0
    assert expected_roi((.5,.2,.3),100)==pytest.approx(.2)


def test_event_balance_duplicate_quote_invariance():
    rows=[dict(event_id='a',v=1),dict(event_id='b',v=0)]
    assert event_balanced(rows+rows[:1]*100,'v')['value']==.5


def test_week_ci_refuses_tiny_cohort_and_conflicting_labels():
    rows=[dict(event_id='a',season=2026,week=1,v=1)]
    assert week_block_ci(rows,'v')['interval'] is None
    with pytest.raises(ValueError):week_block_ci(rows+[dict(rows[0],week=2)],'v')


def test_week_ci_constant_and_reproducible():
    r=[dict(event_id=str(i),season=2026,week=i,v=2.) for i in range(8)]
    assert week_block_ci(r,'v',replicates=100)['interval']==[2,2]
    assert week_block_ci(r,'v',replicates=100)==week_block_ci(r,'v',replicates=100)


def test_actual_line_diagnostic_does_not_merge_away_minus3_with_home_minus3():
    r=dict(event_id='a',market='spread',selection='home',line=-3,p_win=.5,p_push=.1,p_loss=.4,outcome=0)
    rows=offered_line_push_diagnostic([r,dict(r,selection='away',line=3),dict(r,event_id='b',selection='away',line=-3)])
    assert len(rows)==2
    assert rows[0]['predicted_push']['events']==1
    with pytest.raises(ValueError):offered_line_push_diagnostic([dict(r,line=-3.5)])


def ticket():
    return dict(event_id='a',market='spread',decision_time_utc='2026-01-01T00:00:00Z',start_time_utc='2026-01-02T00:00:00Z',source_authenticated=True,stake=1,outcome=0,american_odds=-110)


def test_policy_refunds_push_counts_risk_and_rejects_duplicates():
    t=ticket();kw=dict(policy_frozen_at='2025-12-01T00:00:00Z')
    assert fixed_policy_roi([t],**kw)['roi']==0
    with pytest.raises(ValueError):fixed_policy_roi([t,t],**kw)
    with pytest.raises(ValueError):fixed_policy_roi([dict(t,source_authenticated=False)],**kw)
    with pytest.raises(ValueError):fixed_policy_roi([t],policy_frozen_at='2026-02-01T00:00:00Z')

from research.probability_v2 import calibrate_joint_support,weighted_outcome_masses


def calibrated():
    return calibrate_joint_support([(24,21),(28,21),(20,21)],
      [dict(event_id='a',home_score=24,away_score=21,kickoff='2025-01-01T00:00:00Z',observed_at='2025-01-02T00:00:00Z')],
      key_margins=[3,7],smoothing=3,fitted_through='2025-02-01T00:00:00Z',forecast_cutoff='2026-01-01T00:00:00Z')


def test_joint_calibration_no_atoms_added_and_cross_market_complementarity():
    c=calibrated();assert c['scores']==[(24,21),(28,21),(20,21)]
    assert sum(c['weights'])==pytest.approx(1)
    assert c['weights'][0]==pytest.approx(.5)
    a=weighted_outcome_masses(c,'spread','home',-3)
    b=weighted_outcome_masses(c,'spread','away',3)
    assert a==pytest.approx(b[::-1]);assert a[1]==pytest.approx(.5)
    assert weighted_outcome_masses(c,'total','over',45)==pytest.approx(weighted_outcome_masses(c,'total','under',45)[::-1])


def test_calibration_rejects_unavailable_results_and_unsupported_keys():
    args=dict(key_margins=[3],smoothing=1,fitted_through='2025-02-01T00:00:00Z',forecast_cutoff='2026-01-01T00:00:00Z')
    r=dict(event_id='a',home_score=24,away_score=21,kickoff='2025-01-01T00:00:00Z',observed_at='2025-03-01T00:00:00Z')
    with pytest.raises(ValueError):calibrate_joint_support([(28,21)],[r],**args)
    with pytest.raises(ValueError):calibrate_joint_support([(28,21)],[dict(r,observed_at='2025-01-02T00:00:00Z')],**args)
