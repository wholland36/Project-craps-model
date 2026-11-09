"""Reproduce paired, event-weighted development intervals without fitting."""
import argparse,json
from collections import defaultdict
from pathlib import Path
import numpy as np
from .ncaaf_calibration import verify,calibrate
from .market_audit import checked
from .public_market_validation import digest,write_new


def run(state,archive,output):
    model,reg=verify(state)
    if digest(archive)!=model['source_sha256']:raise ValueError('development archive drift')
    groups=defaultdict(list)
    for line in Path(archive).open():
        q=json.loads(line)
        if q['season'] not in (2024,2025) or q['selection'] not in ('home','over'):continue
        r=checked(q)
        if not r['outcome']:continue
        w,p,l=calibrate([q['p_win'],q['p_push'],q['p_loss']],model['coefficients'][q['market']]['slope'])
        y=r['outcome']==1;base=r['model_conditional_win'];cal=w/(1-p)
        groups[(q['season'],q['market'],q['event_id'])].append(((cal-y)**2-(base-y)**2,base,cal,y))
    results=[]
    for year in (2024,2025):
        for market in ('moneyline','spread','total'):
            gamegroups=[v for (s,m,g),v in groups.items() if (s,m)==(year,market)]
            delta=np.array([np.mean([r[0] for r in rows]) for rows in gamegroups]);rng=np.random.default_rng(20261109)
            draws=[float(delta[rng.integers(0,len(delta),len(delta))].mean()) for _ in range(1000)]
            results.append(dict(season=year,market=market,events=len(delta),paired_event_weighted_brier_delta_challenger_minus_parent=float(delta.mean()),
                descriptive_event_cluster_95pct=np.quantile(draws,[.025,.975]).tolist(),replicates=1000,seed=20261109))
    r=dict(model_sha256=reg['model_sha256'],scope='Already examined development; no untouched or powered confirmation; event CIs omit week dependence and multiplicity',results=results)
    write_new(output,r);return r
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--archive',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(run(a.state,a.archive,a.output),indent=2))
