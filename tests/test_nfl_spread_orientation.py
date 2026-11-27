"""Independent precomputed NFL orientation examples; no historical prices implied."""
import pytest

from project_craps.model import outcome_masses
from research.market_audit import settlement
from research.odds_api_ingest import normalize


@pytest.mark.parametrize(
    'home_score,away_score,home_line,home_result,away_result',
    [(24,21,-3,0,0), (24,21,-3.5,-1,1), (24,21,-2.5,1,-1),
     (17,21,4,0,0), (17,21,3.5,-1,1), (17,21,4.5,1,-1),
     (21,21,0,0,0), (21,21,-.5,-1,1), (21,21,.5,1,-1)],
)
def test_provider_to_grade_and_probability(home_score,away_score,home_line,home_result,away_result):
    snapshot='2026-10-07T19:00:00Z'
    payload={'timestamp':snapshot,'data':[dict(id='TEST',home_team='Home',away_team='Away',
        commence_time='2026-10-07T20:00:00Z',bookmakers=[{'key':'TEST_BOOK','markets':[
            {'key':'spreads','last_update':snapshot,'outcomes':[
                # Deliberately away first and asymmetric prices: never use list order
                # or infer the spread sign from a preferred price.
                {'name':'Away','point':-home_line,'price':-120},
                {'name':'Home','point':home_line,'price':110}]}]}])]}
    rows,rejected=normalize(payload,'NFL')
    assert not rejected and len(rows)==2
    sides={r['selection']:r for r in rows}
    assert sides['home']['line']==home_line and sides['away']['line']==-home_line
    assert sides['home']['american_odds']==110 and sides['away']['american_odds']==-120
    result_bin={1:0,0:1,-1:2}
    fixture=[[home_score,away_score]]
    for side,result in [('home',home_result),('away',away_result)]:
        row=sides[side]; i=result_bin[result]
        assert settlement(dict(row,home_score=home_score,away_score=away_score))==result
        actual=list(outcome_masses(fixture,'spread',side,row['line']))
        assert actual==[int(j==i) for j in range(3)]
