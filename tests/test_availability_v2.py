import copy
import pytest
from research.availability_v2 import administrative_status, allocate_replacements, state_relative_burden, valid_role
CUT='2026-11-05T12:00:00+00:00'
OLD='2026-11-04T12:00:00+00:00'
FUT='2026-11-06T12:00:00+00:00'

def report_policy():
    r=dict(authenticated=True,published_at=OLD,observed_at=OLD,complete=True,eligible_roster_ids=['a'],roster_authenticated=True,roster_complete=True,conference='B10',season=2026,conference_game=True,covered_game=True,kickoff=FUT,statuses={})
    p=dict(authenticated=True,published_at=OLD,observed_at=OLD,conference='B10',season=2026,effective_from='2026-08-01T00:00:00Z',effective_to='2027-01-31T00:00:00Z',omission_means_available=True)
    return r,p

def player(pid,rating=80,position='WR'):
    return dict(player_id=pid,rating=rating,position=position,team='A',rating_iteration='launch',workload=.3,identity_verified=True,role_verified=True,workload_verified=True,published_at=OLD,observed_at=OLD,status='Available')

def test_scoped_omission():
    r,p=report_policy(); x=administrative_status('a',r,p,CUT)
    assert x['status']=='Available' and x['derived'] and not x['full_workload_verified']

@pytest.mark.parametrize('field,value',[('complete',False),('roster_authenticated',False),('roster_complete',False),('conference_game',False),('covered_game',False),('observed_at',FUT),('season',2025),('conference','SEC')])
def test_no_universal_healthy(field,value):
    r,p=report_policy();r[field]=value
    assert administrative_status('a',r,p,CUT)['status']=='Unknown'

def test_policy_and_unknown_boundaries():
    r,p=report_policy()
    assert administrative_status('absent',r,p,CUT)['status']=='Unknown'
    p['omission_means_available']=False
    assert administrative_status('a',r,p,CUT)['status']=='Unknown'
    r['statuses']['a']='Out'
    assert administrative_status('a',r,p,CUT)['status']=='Out'
    p['effective_to']=OLD
    assert administrative_status('a',r,p,CUT)['status']=='Unknown'
    r,p=report_policy()
    assert administrative_status('a',r,p,FUT)['status']=='Unknown'

@pytest.mark.parametrize('n',[1,2,3])
def test_next_three_or_fewer(n):
    loss=player('s',90); roster=[loss]+[player(str(i),80-i) for i in range(n)]
    x=allocate_replacements([loss],roster,CUT)[0]
    assert x['resolved'] and len(x['replacement_ids'])==n
    assert x['replacement_rating']==sum(80-i for i in range(n))/n

def test_strict_lower_and_available():
    loss=player('s',90);out=player('out',85);out['status']='Out'
    x=allocate_replacements([loss],[loss,player('equal',90),player('higher',95),out,player('ok',80)],CUT)[0]
    assert x['replacement_ids']==['ok']

def test_joint_pool_capacity():
    a,b=player('a',90),player('b',89)
    x=allocate_replacements([a,b],[a,b]+[player(str(i),80-i) for i in range(5)],CUT)
    assert [len(r['replacement_ids']) for r in x]==[3,2]
    assert not set(x[0]['replacement_ids']) & set(x[1]['replacement_ids'])

def test_actual_first_and_capacity():
    a,b=player('a',90),player('b',89)
    for p in (a,b):p.update(actual_replacement_id='backup',actual_replacement_verified=True,replacement_published_at=OLD,replacement_observed_at=OLD)
    x=allocate_replacements([a,b],[a,b,player('backup',95)],CUT)
    assert x[0]['replacement_rating']==95 and x[0]['burden']==0
    assert not x[1]['resolved']

def test_actual_future_no_fallback():
    a=player('a',90);a.update(actual_replacement_id='b',actual_replacement_verified=True,replacement_published_at=FUT,replacement_observed_at=FUT)
    assert not allocate_replacements([a],[a,player('b',80)],CUT)[0]['resolved']

def test_qb_requires_verified_replacement():
    a=player('a',90,'QB')
    assert not allocate_replacements([a],[a,player('b',80,'QB')],CUT)[0]['resolved']

@pytest.mark.parametrize('field,value',[('identity_verified',False),('role_verified',False),('workload',None),('workload',float('nan')),('rating',100),('observed_at',FUT)])
def test_role_guards(field,value):
    a=player('a');a[field]=value;assert valid_role(a,CUT)

def test_duplicate_ids():
    a=player('a')
    with pytest.raises(ValueError):allocate_replacements([a],[a,a],CUT)

def test_baseline_recursion_and_asymmetric_return():
    a=state_relative_burden(10,0);assert a['incremental_burden']==10 and a['next_embedded_burden']==1.5
    b=state_relative_burden(10,a['next_embedded_burden']);assert b['incremental_burden']==8.5
    c=state_relative_burden(10,b['next_embedded_burden'],role_restoration=.5)
    assert c['incremental_burden']==pytest.approx(2.225)
    assert c['scoring_points'] is None and not c['elo_changed']
    assert state_relative_burden(None,1)['incremental_burden'] is None
    with pytest.raises(ValueError):state_relative_burden(1,0,role_restoration=2)

def test_primary_prior_independent_of_greedy_depletion():
    a,b=player('a',90),player('b',89)
    x=allocate_replacements([a,b],[a,b]+[player(str(i),80-i) for i in range(3)],CUT)
    assert x[0]['primary_replacement_ids']==x[1]['primary_replacement_ids']==['0','1','2']
    assert x[0]['primary_replacement_rating']==x[1]['primary_replacement_rating']==79
    assert x[1]['primary_prior_resolved'] and not x[1]['resolved']
    assert x[1]['primary_burden']==3

def test_crosswalk_and_coverage():
    from research.availability_v2 import build_identity_crosswalk, known_unknown_coverage
    r=dict(espn_id='1',ea_id='2',team='A',season=2026,normalized_name='John Smith',evidence_ref='receipt',identity_verified=True)
    assert build_identity_crosswalk([r])==[r]
    with pytest.raises(ValueError):build_identity_crosswalk([r,dict(r,espn_id='3',ea_id='4')])
    with pytest.raises(ValueError):build_identity_crosswalk([dict(r,evidence_ref='')])
    assert known_unknown_coverage([{'resolved':True},{'missing_flags':['unknown']}])['unresolved']==1
    assert known_unknown_coverage([])['resolved_fraction'] is None

def test_uncertainty_and_verified_lineup():
    from research.availability_v2 import uncertain_scenarios, verified_ol_continuity
    assert uncertain_scenarios(0,10)['expected_burden'] is None
    with pytest.raises(ValueError):uncertain_scenarios(0,10,.5)
    a=dict(verified=True,published_at=OLD,observed_at=OLD,slots=dict(LT='1',LG='2',C='3',RG='4',RT='5'))
    b=copy.deepcopy(a);b['slots']['C']='6'
    assert verified_ol_continuity(a,b,CUT)['unchanged_slots']==4
    b['observed_at']=FUT
    assert verified_ol_continuity(a,b,CUT)['unchanged_slots'] is None
