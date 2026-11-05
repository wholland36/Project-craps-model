import math
import pytest
from research.beta_v2.calibration import fit,apply,proper_scores

P={'model_sha256':'abc','version':'strength-v2','schema':'scores-v1'}
def rows():
    return [dict(event_id=str(i),sport='NFL',parent_train_cutoff='2024-01-01T00:00:00Z',kickoff='2025-01-01T00:00:00Z',result_observed_at='2025-01-02T00:00:00Z',home_score=24,away_score=21,predicted_margin=2,predicted_total=45,scores=[[24,21],[17,20],[28,14],[21,21]]) for i in range(30)]
def test_fit_coherent_parent_binding():
    a=fit(rows(),'NFL','2025-12-31T00:00:00Z',P)
    x=apply(rows()[0]['scores'],a,dict(predicted_margin=2,predicted_total=45,parent=P))
    assert sum(x['weights'])==pytest.approx(1)
    assert x['weights'][0]>0.25
    with pytest.raises(ValueError,match='binding'): apply(rows()[0]['scores'],a,dict(predicted_margin=2,predicted_total=45,parent=dict(P,model_sha256='bad')))
def test_oof_leakage_rejected():
    r=rows();r[0]['parent_train_cutoff']=r[0]['kickoff']
    with pytest.raises(ValueError,match='chronological'): fit(r,'NFL','2025-12-31T00:00:00Z',P)
def test_support_failure_explicit():
    r=rows();r.append(dict(r[0],event_id='fail',home_score=0,away_score=1))
    a=fit(r,'NFL','2025-12-31T00:00:00Z',P)
    assert a['support_failures'][0]['event_id']=='fail'
    assert a['supported_fit_games']==30

def test_ncaab_no_ties():
    r=rows();r[0]['sport']='NCAAB'
    with pytest.raises(ValueError,match='ties'): fit(r,'NCAAB','2025-12-31T00:00:00Z',P)
def test_logloss_support_and_push():
    s=proper_scores([0,0.1,0.9],0)
    assert s['logloss_is_infinite'] and s['threeway_logloss'] is None
    assert proper_scores([0.4,0.2,0.4],1)['conditional_brier'] is None
    assert proper_scores([0.4,0.2,0.4],0)['conditional_brier']==pytest.approx(0.25)

def test_evaluation_preserves_infinite_support_report():
    import json
    from research.beta_v2.calibration import evaluate
    a=fit(rows(),'NFL','2025-12-31T00:00:00Z',P)
    future=dict(rows()[0],event_id='future',kickoff='2026-01-01T00:00:00Z',home_score=0,away_score=1,evaluation_lines=[{'market':'total','line':1}])
    report=evaluate([future],a)
    json.dumps(report,allow_nan=False)
    assert report['roi'] is None
    assert report['markets']['total']['raw_parent']['infinite_logloss_count']==1
