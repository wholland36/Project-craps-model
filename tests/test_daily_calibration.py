import pytest
from research.daily_calibration import fit,apply,category,category_probabilities


def rows():
    return [dict(event_id=str(i),kickoff='2025-01-01T00:00:00Z',result_observed_at='2025-01-02T00:00:00Z',forecast_category_probabilities=[.05,.05,.05,.05,.8],actual_margin=3 if i<15 else 10) for i in range(40)]


def test_actual_fit_frozen_and_deterministic():
    a=fit(rows(),'NCAAF','2026-01-01T00:00:00Z')
    assert a==fit(rows(),'NCAAF','2026-01-01T00:00:00Z')
    assert a['training_objective_after']<a['training_objective_before']
    assert a['offsets'][2]>a['offsets'][4]


def test_apply_support_weights_and_sport_tie_semantics():
    a=fit(rows(),'NCAAF','2026-01-01T00:00:00Z');s=[(24,21),(31,21),(10,17)]
    c=apply(s,a);assert c['scores']==s;assert sum(c['weights'])==pytest.approx(1)
    assert c['weights'][0]>c['weights'][1]
    with pytest.raises(ValueError):apply([(21,21)],a)
    assert category(0,'NFL')==0
    with pytest.raises(ValueError):category(0,'NCAAB')


def test_no_future_outcomes_duplicates_or_unknown_support():
    r=rows()
    with pytest.raises(ValueError):fit(r,'NCAAF','2024-01-01T00:00:00Z')
    with pytest.raises(ValueError):fit(r+[r[0]],'NCAAF','2026-01-01T00:00:00Z')
    r[0]['forecast_category_probabilities']=[0,0,0,0,1]
    with pytest.raises(ValueError):fit(r,'NCAAF','2026-01-01T00:00:00Z')


def test_basketball_bins_no_football_keys_and_football_mirror():
    assert category(3,'NCAAB')==category(1,'NCAAB')
    assert category(7,'NCAAB')==category(10,'NCAAB')
    assert category(-3,'NCAAF')!=category(3,'NCAAF')
    assert category_probabilities([(21,21),(24,21)],'NFL')[0]==.5


def test_fit_depends_on_each_games_forecast_not_just_truth_frequency():
    a=fit(rows(),'NCAAF','2026-01-01T00:00:00Z')
    r=rows()
    for row in r:row['forecast_category_probabilities']=[.05,.05,.35,.05,.5]
    b=fit(r,'NCAAF','2026-01-01T00:00:00Z')
    assert abs(a['offsets'][2]-b['offsets'][2])>.1


def test_reject_nonfinite_negative_and_half_scores():
    a=fit(rows(),'NCAAF','2026-01-01T00:00:00Z')
    for s in [[(20.5,10)],[(float('nan'),10)],[(-1,2)]]:
        with pytest.raises(ValueError):apply(s,a)
