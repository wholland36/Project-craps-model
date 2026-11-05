import pytest
from research.non_qb_replacement import replacement_prior

def player(i,r,position='WR',team='1',iteration='1-base'):
    return dict(ea_player_id=str(i),overall_rating=r,position_group=position,ea_team_id=team,iteration=iteration)

def test_next_three_and_unavailable():
    p=player(1,90);roster=[p,player(2,89),player(3,85),player(4,80),player(5,75),player(6,99),player(7,84,team='2')]
    r=replacement_prior(p,roster,['2'])
    assert r['replacement_ids']==['3','4','5'] and r['rating_gap']==10
    assert r['scoring_point_adjustment'] is None

def test_verified_better_replacement_has_priority():
    p=player(1,80);r=replacement_prior(p,[p,player(2,90)],verified_replacement='2')
    assert r['method']=='VERIFIED_REPLACEMENT' and r['rating_gap']==-10 and r['nonnegative_rating_loss']==0

def test_incomplete_and_no_mixed_vintage_or_position():
    p=player(1,90);r=replacement_prior(p,[p,player(2,80),player(3,70,position='TE'),player(4,70,iteration='week8')])
    assert r['replacement_count']==1 and r['replacement_rating']==80
    assert replacement_prior(p,[p])['status']=='INCOMPLETE'

def test_qb_duplicate_invalid_and_out_verified():
    with pytest.raises(ValueError): replacement_prior(player(1,90,'QB'),[])
    p=player(1,90)
    with pytest.raises(ValueError): replacement_prior(p,[p,p])
    with pytest.raises(ValueError): replacement_prior(p,[p,player(2,100)])
    with pytest.raises(ValueError): replacement_prior(p,[p,player(2,80)],['2'],verified_replacement='2')


def test_two_available_average():
    p=player(1,90);r=replacement_prior(p,[p,player(2,80),player(3,70)])
    assert r['replacement_count']==2 and r['replacement_rating']==75
