import copy
import math
import pytest
from research.beta_support_v3 import (geometric_masses, project, training_support,
    correction_view, confirmation_allowed, POLICY)
from research.beta_v2.calibration import proper_scores

def brute(mh,ma,market,side,line=None):
    qh,qa=mh/(mh+1),ma/(ma+1); masses=[0.,0.,0.]; norm=0.
    for h in range(140):
        for a in range(140):
            if h==a:continue
            w=(1-qh)*(1-qa)*qh**h*qa**a;norm+=w
            if market=='moneyline':v=(h-a)*(1 if side=='home' else -1)
            elif market=='spread':v=(h-a)*(1 if side=='home' else -1)+line
            else:v=(h+a-line)*(1 if side=='over' else -1)
            masses[0 if v>0 else 1 if v==0 else 2]+=w
    return [p/norm for p in masses]

@pytest.mark.parametrize('m,s,l',[('moneyline','home',None),('moneyline','away',None),
    ('spread','home',-3),('spread','away',3),('spread','home',3.5),
    ('total','over',8),('total','under',8),('total','over',8.5),('total','under',.5)])
def test_joint_projection_matches_independent_enumeration(m,s,l):
    assert geometric_masses(4,6,m,s,l)==pytest.approx(brute(4,6,m,s,l),abs=1e-8)

@pytest.mark.parametrize('line',[-500,-3.5,-3,0,3,500])
def test_spread_complements_and_extreme_support(line):
    h=geometric_masses(70,75,'spread','home',line)
    a=geometric_masses(70,75,'spread','away',-line)
    assert h==pytest.approx(list(reversed(a)))
    assert h[0]>0 and h[2]>0 and sum(h)==pytest.approx(1)

def test_total_push_and_impossible_tie():
    assert geometric_masses(70,75,'moneyline','home')[1]==0
    assert geometric_masses(70,75,'total','over',140)[1]>0
    assert geometric_masses(70,75,'total','over',140.5)[1]==0
    assert geometric_masses(70,75,'total','under',.5)[0]==0

def test_tail_repairs_feasible_zero_without_clipping_parent():
    c={'scores':[[60,90],[61,90]],'weights':[.5,.5]};before=copy.deepcopy(c)
    v=project(c,'spread','home',-3)
    assert v[0]>0 and not proper_scores(v,0)['logloss_is_infinite']
    assert c==before and sum(v)==pytest.approx(1)
    # Same probability model produces matching complements across each market.
    assert project(c,'spread','away',3)==pytest.approx(list(reversed(v)))

def rows():
    return [dict(event_id=str(i),home_id='H',away_id='A',kickoff='2025-01-01T00:00Z',result_observed_at='2025-01-02T00:00Z') for i in range(5)]

def test_gate_blocks_sparse_and_disconnected():
    r=rows()+[dict(rows()[0],event_id='other',home_id='X',away_id='Y')]
    g=training_support(r,'H','X','2025-02-01T00:00Z')
    assert set(g['reasons'])=={'disconnected_training_components','insufficient_prior_team_games'}
    assert training_support(rows(),'H','A','2025-02-01T00:00Z')['supported']
    assert not training_support(rows(),'H','NEW','2025-02-01T00:00Z')['supported']

def test_gate_refuses_future_results_and_duplicate_rows():
    with pytest.raises(ValueError,match='availability'):training_support(rows(),'H','A','2024-12-31T00:00Z')
    with pytest.raises(ValueError,match='duplicate'):training_support(rows()+rows(),'H','A','2025-02-01T00:00Z')

def test_corrections_cannot_clear_time_revision_or_promotion():
    identity=dict(home_id='H',away_id='A',kickoff='2025-01-01T00:00Z')
    original=dict(identity=identity);current=dict(identity,home_score=89,away_score=67)
    evidence=dict(independent_source='school',captured_at='2025-01-02T00:00Z',sha256='a',home_score=89,away_score=67)
    view=correction_view(original,current,evidence)
    assert view['status']=='CORROBORATED_DESCRIPTIVE_VIEW' and not view['eligible_for_approval']
    assert correction_view(original,dict(current,kickoff='2025-01-01T01:00Z'),evidence)['status']=='QUARANTINED'
    assert correction_view(original,current,dict(evidence,away_score=69))['status']=='QUARANTINED'

def test_confirmation_never_opens_on_game_count():
    for e in ['old','new']:
        assert not confirmation_allowed(e,{'excluded_events':['old']},dict(games=10000))['allowed']

@pytest.mark.parametrize('args',[(70,75,'total','over',-1),(70,75,'spread','home',3.25),(70,75,'moneyline','home',3),(0,75,'spread','home',-3)])
def test_invalid_tail_inputs_rejected(args):
    with pytest.raises(ValueError):geometric_masses(*args)

def test_immutable_record_integrity(tmp_path):
    from research.beta_support_v3 import create, verified_read
    p=tmp_path/'record.json';create(p,{'value':1})
    assert verified_read(p)=={'value':1}
    with pytest.raises(FileExistsError):create(p,{'value':2})
    p.write_text(p.read_text().replace('"value":1','"value":2'))
    with pytest.raises(ValueError,match='drift'):verified_read(p)

def test_grade_rejects_late_or_revised_results():
    from research.beta_support_v3 import grade_record
    r=dict(event_id='1',horizon='FINAL',issued_at='2026-11-07T15:00Z',identity=dict(home_id='H',away_id='A',neutral=False,kickoff='2026-11-07T16:00Z'),masses={'moneyline:home:None':[.4,0,.6]},paired_fresh_parent_masses={'moneyline:home:None':[0,0,1]},support={'supported':True},confirmation={'allowed':False})
    e=dict(r['identity'],event_id='1',status='FINAL',observed_at='2026-11-07T19:00Z',home_score=80,away_score=75)
    reg=dict(registered_at='2026-11-07T14:00Z')
    g=grade_record(r,e,reg)
    assert not g['grades']['support_v3']['moneyline:home:None']['logloss_is_infinite']
    assert g['grades']['paired_parent']['moneyline:home:None']['logloss_is_infinite']
    for changed in [dict(e,neutral=True),dict(e,kickoff='2026-11-07T16:45Z'),dict(e,event_id='2')]:
        with pytest.raises(ValueError,match='revision'):grade_record(r,changed,reg)
    with pytest.raises(ValueError,match='clocks'):grade_record(r,e,{'registered_at':'2026-11-07T15:01Z'})
