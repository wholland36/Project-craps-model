"""Public ESPN summary audit; private raw bodies, retrospective source receipts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import urllib.request


def _score_int(value):
    if isinstance(value, bool):
        raise ValueError('boolean score')
    if isinstance(value, str):
        if not value.isascii() or not value.isdigit():
            raise ValueError('noninteger score string')
        return int(value)
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or int(value) != value:
        raise ValueError('noninteger score')
    return int(value)


def parse_summary(body, expected):
    comp=body.get('header',{}).get('competitions',[{}])[0]
    flags=[]
    if str(comp.get('id')) != str(expected['event_id']): flags.append('event_id_mismatch')
    teams={c.get('homeAway'):c for c in comp.get('competitors',[])}
    for side in ('home','away'):
        if str(teams.get(side,{}).get('id')) != str(expected.get(side+'_id')): flags.append(side+'_id_mismatch')
    if not comp.get('status',{}).get('type',{}).get('completed'): flags.append('not_final')
    if comp.get('date') != expected.get('kickoff'):
        try:
            if datetime.fromisoformat(comp['date'].replace('Z','+00:00')) != datetime.fromisoformat(expected['kickoff'].replace('Z','+00:00')):flags.append('kickoff_mismatch')
        except (KeyError,ValueError):flags.append('kickoff_unknown')
    result={'event_id':str(expected['event_id']),'retrospective_only':True,'identity_flags':flags,'original_publication_at':None,'original_completion_at':None,'regulation_score':None,'overtime':None,'observed_drive_count':0,'observed_play_rows':0,'complete_drive_count':None,'complete_play_count':None,'possession_count':None,'drive_coverage':'NOT_ESTABLISHED','garbage_time_filter':'NOT_APPLIED','kneel_filter':'NOT_APPLIED'}
    scores={};lengths=[]
    try:
        for side in ('home','away'):
            ls=teams[side]['linescores'];lengths.append(len(ls))
            if len(ls)<4:raise ValueError('missing regulation periods')
            vals=[_score_int(v.get('value',v.get('displayValue'))) for v in ls]
            if any(v<0 for v in vals) or sum(vals)!=_score_int(teams[side]['score']):raise ValueError('period scores disagree final')
            scores[side]=sum(vals[:4])
        if len(set(lengths))!=1:raise ValueError('unequal period counts')
        if not flags:result['regulation_score']=scores;result['overtime']=lengths[0]>4
    except (KeyError,ValueError,TypeError):result['period_score_flags']=['incomplete_or_inconsistent_period_scores']
    ds=body.get('drives',{});previous=ds.get('previous',[])
    if not isinstance(previous,list):previous=[]
    plays=[p for d in previous for p in d.get('plays',[]) if isinstance(p,dict)]
    result['observed_drive_count']=len(previous);result['observed_play_rows']=len(plays)
    ids=[p.get('id') for p in plays];drive_ids=[d.get('id') for d in previous]
    checks={'unique_play_ids':bool(ids) and None not in ids and len(set(ids))==len(ids),'unique_drive_ids':bool(drive_ids) and None not in drive_ids and len(set(drive_ids))==len(drive_ids),'every_drive_has_plays':bool(previous) and all(d.get('plays') for d in previous),'no_current_drive':not ds.get('current')}
    # ESPN summary has no trusted full-feed completeness/pagination attestation.
    # Internal consistency is useful but cannot prove omitted drives do not exist.
    result['drive_internal_checks']=checks
    result['drive_coverage_flags']=['source_has_no_verified_complete_feed_attestation']
    if not all(checks.values()):result['drive_coverage_flags'].append('internally_incomplete_or_duplicate_drive_feed')
    result['possession_definition']='Unknown; drive records are not automatically complete possessions'
    return result


def collect(cohort, private_dir, output_dir, reuse_dirs=(), workers=8):
    private_dir=Path(private_dir);private_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    cached={}
    for folder in reuse_dirs:
        folder=Path(folder)
        receipt=folder/'summary-receipts.jsonl'
        if receipt.exists():
            for line in receipt.read_text().splitlines():
                try:
                    r=json.loads(line); f=folder/'game-summaries'/(str(r['event_id'])+'.json')
                    if f.exists() and hashlib.sha256(f.read_bytes()).hexdigest()==r.get('sha256'):cached.setdefault(str(r['event_id']),(f,r))
                except (KeyError,ValueError):pass
    def one(g):
        eid=str(g['event_id']);url='https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event='+eid
        receipt={'event_id':eid,'url':url,'original_publication_at':None,'original_completion_at':None,'historical_pregame_proof':False}
        try:
            if eid in cached:
                f,old=cached[eid];raw=f.read_bytes();receipt.update(reused_verified_body=True,observed_at=old.get('observed_at'),reused_from=str(f),new_network_call=False)
            else:
                with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'ProjectCrapsResearch/2'}),timeout=25) as response:raw=response.read()
                receipt.update(reused_verified_body=False,observed_at=datetime.now(timezone.utc).isoformat(),new_network_call=True)
            body=json.loads(raw);parsed=parse_summary(body,g)
            dest=private_dir/(eid+'.json');dest.write_bytes(raw);dest.chmod(0o600)
            receipt.update(sha256=hashlib.sha256(raw).hexdigest(),status='DERIVED',capture_class='RETROSPECTIVE',derived_at=datetime.now(timezone.utc).isoformat())
            return parsed,receipt
        except Exception as exc:
            receipt.update(status='ERROR_NO_RETRY',error_type=type(exc).__name__,observed_at=datetime.now(timezone.utc).isoformat())
            return {'event_id':eid,'retrospective_only':True,'error_type':type(exc).__name__},receipt
    with ThreadPoolExecutor(max_workers=min(8,max(1,workers))) as pool: pairs=list(pool.map(one,cohort))
    results=[p[0] for p in pairs];receipts=[p[1] for p in pairs]
    audit={'games_retained':len(cohort),'summaries_derived':sum(r['status']=='DERIVED' for r in receipts),'errors':sum(r['status']!='DERIVED' for r in receipts),'network_calls':sum(r.get('new_network_call',False) for r in receipts),'verified_reuses':sum(r.get('reused_verified_body',False) for r in receipts),'regulation_score_games':sum(r.get('regulation_score') is not None for r in results),'overtime_games':sum(r.get('overtime') is True for r in results),'identity_quarantined_games':sum(bool(r.get('identity_flags')) for r in results),'observed_drive_rows':sum(r.get('observed_drive_count',0) for r in results),'observed_play_rows':sum(r.get('observed_play_rows',0) for r in results),'complete_possession_games':0,'complete_drive_feed_games':0,'historical_pregame_authentication':False,'all_results_retrospective':True,'no_fit_or_promotion':True,'collector_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (private_dir/'source-receipts.json').write_text(json.dumps(receipts,indent=2)+'\n')
    # Public receipts omit local raw-source paths and have no raw odds.
    public=[{k:v for k,v in r.items() if k!='reused_from'} for r in receipts]
    for name,value in [('game-input-audit.json',audit),('derived-game-inputs.json',results),('source-receipts.json',public)]:
        (output_dir/name).write_text(json.dumps(value,indent=2)+'\n')
    return audit


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cohort',required=True);p.add_argument('--private-dir',required=True);p.add_argument('--output-dir',required=True);p.add_argument('--reuse-dir',action='append',default=[])
    a=p.parse_args();print(json.dumps(collect(json.loads(Path(a.cohort).read_text()),a.private_dir,a.output_dir,a.reuse_dir),indent=2))
