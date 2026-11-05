"""Run data readiness without refitting frozen models or fabricating missing inputs."""
import argparse
import json
from collections import Counter
from pathlib import Path
from .validation_v2 import production_gate, sha, canonical


def audit_games(games):
    ids=[str(g['event_id']) for g in games]
    if len(set(ids))!=len(ids):raise ValueError('duplicate event identity')
    counts=Counter();rows=[]
    for g in games:
        sides=g['sides'];n=sum(bool(s.get('report_present')) for s in sides.values())
        coverage=('no_report','one_team_report','both_team_reports')[n]
        unresolved=sum(len(s.get('unresolved_inputs',[])) for s in sides.values())
        resolved=sum(len(s.get('resolved_players',[])) for s in sides.values())
        supported=g.get('baseline') is not None
        label='unsupported_baseline' if not supported else coverage
        counts[label]+=1
        rows.append(dict(event_id=g['event_id'],week=g['week'],retained=True,baseline_supported=supported,
            report_coverage=coverage,unresolved_contributions=unresolved,resolved_player_rows=resolved,
            numerical_zero_is_not_healthy=True,
            feature_readiness=dict(injury_value='PARTIAL_KNOWN_INPUT_ONLY' if resolved else 'UNRESOLVED_OR_NO_CHANGED_EXPOSURE',
                qb_value='NOT_IDENTIFIED',ol_defensive_workload='UNRESOLVED',weather_forecast_vintage='UNRESOLVED',
                independent_pregame_momentum='UNRESOLVED',trap='DESCRIPTIVE_RETROSPECTIVE_ONLY'),
            source_authentication='NOT_INDEPENDENTLY_ESTABLISHED',actionable=False))
    return dict(games_retained=len(rows),coverage_counts=dict(counts),games=rows,
        production_gate=production_gate({}),fitting_performed=False,
        limitations=['No new scoring coefficients or probabilities inferred from unavailable inputs',
            'All historical games retained; unresolved contributions ignored with flags',
            'Existing inspected later cohort is development only'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--games',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raw=a.games.read_bytes();result=audit_games(json.loads(raw));result['source_sha256']=sha(raw)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('xb') as f:f.write(canonical(result))
    print(json.dumps({k:v for k,v in result.items() if k!='games'}))

if __name__=='__main__':main()
