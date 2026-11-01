"""Report only immutable first prospective experiment records; no wager P&L."""
import argparse
import json
from collections import defaultdict
from project_craps.common import create,stamp,now
from research.store import ShadowStore


def report(path,output):
    store=ShadowStore(path)
    try:
        rows=store.records();first=[r for r in rows if r['first_shadow_key']==r['key']]
        known={r['key']:r for r in first};scores=defaultdict(list)
        for _,payload,_ in store.db.execute('SELECT * FROM results'):
            result=json.loads(payload)
            if result['key'] not in known:continue
            record=known[result['key']]
            for variant,metrics in result['scores'].items():scores[(record['sport'],variant)].append(metrics)
        result={'reported_at':stamp(now()),'all_records':len(rows),'unique_first_event_records':len(first),
                'sports':{sport:sum(r['sport']==sport for r in first) for sport in ['NFL','NCAAF']},
                'settled_first_event_records':sum(1 for key, in store.db.execute('SELECT key FROM results') if key in known),
                'metrics':{},'anchor':store.verify(),'approved_risk':0,'official_pnl':0,
                'warning':'Private unadjusted shadow forecasts only. Missing material inputs remain unadjusted; no approved probabilities or wagers.'}
        for (sport,variant),values in scores.items():
            result['metrics'][sport+':'+variant]={'n':len(values),
                 'brier':sum(v['home_win_brier'] for v in values)/len(values),
                 'logloss':sum(v['home_win_logloss'] for v in values)/len(values),
                 'promotion':'NONE; preregistered independent evidence review still required'}
        create(output,result);return result
    finally:store.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--registry',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=report(a.registry,a.output);print('Forward cohort:',r['unique_first_event_records'],'unique events,',r['settled_first_event_records'],'settled')

if __name__=='__main__':main()
