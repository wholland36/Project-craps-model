"""Conservative incremental injury research; never official model promotion."""
import hashlib,json,math,os,uuid
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from scipy.optimize import lsq_linear
GROUPS=('QB','RUSH','RECEIVE')


def shock(current, previous):
    states={'Available':0.,'Out':1.}
    if current not in states or previous not in states:return None
    return states[current]-states[previous]


def workload_share(player, games):
    """Aggregated observed opportunities from earlier healthy games, not snaps."""
    if not games:return None
    total=0.;own=0.
    for g in games:
        values=g['opportunities']
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values.values()):raise ValueError('invalid opportunity count')
        total+=sum(values.values());own+=values.get(player,0.)
    return own/total if total>0 else None


def aggregate(players):
    """Cap joint group workload; retain shared estimated backup pool flags."""
    features={g:0. for g in GROUPS};caps={};shared={};counts={g:0 for g in GROUPS}
    for group in GROUPS:
        rows=[r for r in players if r['group']==group];shares=[];uses={}
        for r in rows:
            if r['shock'] not in [-1.,1.] or not math.isfinite(r['gap']) or r['gap']<0 or not math.isfinite(r['workload']) or not 0<=r['workload']<=1:raise ValueError('invalid resolved shock')
            shares.append(r['workload'])
            for pid in r['replacement_ids']:uses[pid]=uses.get(pid,0)+1
        divisor=max(1.,sum(shares));caps[group]=divisor;counts[group]=len(rows)
        features[group]=sum(r['gap']*r['workload']/divisor*r['shock'] for r in rows)
        shared[group]={pid:n for pid,n in uses.items() if n>1}
    return {'signed_loss_by_group':features,'workload_cap_divisor':caps,'resolved_changed_players':counts,'shared_backup_ids':shared}


def fit_nonnegative(X,y,alpha):
    X=np.asarray(X,dtype=float);y=np.asarray(y,dtype=float)
    if X.ndim!=2 or X.shape[1]!=3 or len(X)!=len(y) or len(y)<2 or not np.isfinite(X).all() or not np.isfinite(y).all() or not math.isfinite(alpha) or alpha<=0:raise ValueError('invalid training input')
    mu=X.mean(0);scale=X.std(0);scale[scale==0]=1.;z=(X-mu)/scale;bias=y.mean()
    aug=np.vstack([z,np.sqrt(alpha)*np.eye(3)]);target=np.r_[y-bias,np.zeros(3)]
    result=lsq_linear(aug,target,bounds=(0,np.inf),tol=1e-12)
    if not result.success:raise ValueError('constrained fit failed')
    raw=np.maximum(0.,result.x/scale)
    # An unobserved feature is not identified, regardless of optimizer tolerance.
    raw[np.std(X,axis=0)==0]=0.
    if np.all(z.T@(y-bias)<=0):raw[:]=0.
    raw[np.abs(raw)<1e-10]=0.
    return {'groups':list(GROUPS),'raw_coefficients':raw.tolist(),'intercept':float(bias-mu@raw),'alpha':alpha,'training_n':len(y),'production_approved':False}


def correction(model, features):
    co=np.asarray(model['raw_coefficients'],dtype=float);x=np.asarray([features[g] for g in GROUPS],dtype=float)
    if co.shape!=(3,) or not np.isfinite(co).all() or np.any(co<0) or not np.isfinite(x).all():raise ValueError('invalid candidate coefficients/features')
    return float(model['intercept']+x@co)


def digest(data):return hashlib.sha256(data).hexdigest()
def instant(s):
    value=datetime.fromisoformat(s.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('timezone required')
    return value


def capture_snapshot(folder,url,body):
    """Local observation receipt; source identity still requires external review."""
    if not url.startswith(('https://','local-artifact:')) or not isinstance(body,bytes):raise ValueError('HTTPS URL and bytes required')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True,mode=0o700);key=uuid.uuid4().hex
    raw=folder/(key+'.snapshot');receipt=folder/(key+'.receipt.json')
    with raw.open('xb') as f:f.write(body)
    raw.chmod(0o600)
    result={'url':url,'sha256':digest(body),'snapshot_path':str(raw.resolve()),'observed_at':datetime.now(timezone.utc).isoformat(),'publication_at':None,'independent_source_authentication':False}
    with receipt.open('x') as f:json.dump(result,f,indent=2)
    receipt.chmod(0o600)
    return {'receipt_path':str(receipt.resolve())}


def verify_snapshot(source,cut):
    receipt=json.loads(Path(source['receipt_path']).read_text())
    if not receipt['url'].startswith(('https://','local-artifact:')) or digest(Path(receipt['snapshot_path']).read_bytes())!=receipt['sha256']:raise ValueError('source snapshot hash mismatch')
    if instant(receipt['observed_at'])>cut:raise ValueError('future source observation')
    return receipt


def register_forecast(folder, artifact_path, record):
    """Separate immutable shadow record; reconstruct features, verify source bytes."""
    artifact_path=Path(artifact_path);data=artifact_path.read_bytes();model=json.loads(data)
    now=datetime.now(timezone.utc);cut=instant(record['cutoff']);kick=instant(record['kickoff']);frozen=instant(model['frozen_at'])
    if not frozen<=cut<=now<kick:raise ValueError('forecast must be frozen and captured before kickoff')
    if record['season']!=model['prospective_season'] or not instant(model['prospective_start'])<=kick<instant(model['prospective_end']):raise ValueError('outside frozen evaluation season/horizon')
    if record['baseline_model_sha256']!=model['baseline_model_sha256']:raise ValueError('baseline hash mismatch')
    if record.get('baseline_expected_home_margin') is None:raise ValueError('baseline mean required')
    if not record.get('sources'):raise ValueError('sources required even when injury contributions omitted')
    verified=[verify_snapshot(source,cut) for source in record['sources']]
    if record.get('feature_code_sha256')!=model['feature_code_sha256'] or digest(Path(__file__).read_bytes())!=model['feature_code_sha256']:raise ValueError('candidate feature code changed after freeze')
    if digest(Path(model['protocol_path']).read_bytes())!=model['protocol_sha256']:raise ValueError('frozen protocol changed')
    if 'missing_inputs' not in record:raise ValueError('explicit missing-input flags required')
    if record.get('feature_audit_status')!='CALLER_RECONSTRUCTED_FROM_SNAPSHOTS_NOT_INDEPENDENTLY_AUTHENTICATED':raise ValueError('feature source audit status required')
    resolved=record['resolved_player_shocks']
    for side in ['home','away']:
        for r in resolved[side]:
            if shock(r['current_status'],r['previous_status'])!=r['shock']:raise ValueError('status/feature conflict')
            healthy=r['healthy_games']
            if not 1<=len(healthy)<=3:raise ValueError('healthy workload history required')
            for g in healthy:
                age=cut-instant(g['kickoff'])
                if g['status']!='Available' or not 48*3600<=age.total_seconds()<=42*86400:raise ValueError('invalid healthy workload cutoff')
            estimate=workload_share(r['player_key'],healthy)
            if estimate is None or abs(estimate-r['workload'])>1e-10:raise ValueError('workload mismatch')
    h=aggregate(resolved['home']);a=aggregate(resolved['away']);x={g:a['signed_loss_by_group'][g]-h['signed_loss_by_group'][g] for g in GROUPS}
    if any(abs(record['features'][g]-x[g])>1e-10 for g in GROUPS):raise ValueError('features do not match resolved player records')
    baseline=record['baseline_expected_home_margin'];delta=correction(model['shadow_injury_model'],x);selected=correction(model['selected_research_model'],x)
    out=dict(record,registered_at=now.isoformat(),candidate_sha256=digest(data),record_kind='PROSPECTIVE_RESEARCH_ONLY',verified_observation_receipts=verified,independent_source_authentication=False,shadow_correction=delta,shadow_expected_home_margin=baseline+delta,selected_research_expected_home_margin=baseline+selected,train_mean_expected_home_margin=baseline+model['benchmarks']['train_mean_intercept'],train_median_expected_home_margin=baseline+model['benchmarks']['train_median_intercept'],production_approved=False,approved_risk_usd=0)
    if not all(math.isfinite(out[k]) for k in ['shadow_expected_home_margin','selected_research_expected_home_margin','train_mean_expected_home_margin','train_median_expected_home_margin']):raise ValueError('invalid baseline mean')
    key=record['event_id']
    if not key or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in key):raise ValueError('unsafe event ID')
    folder=Path(folder)
    if not folder.name.startswith('injury-shock-'):raise ValueError('separate named injury-shock research registry required')
    folder.mkdir(parents=True,exist_ok=True);path=folder/(key+'.json')
    with path.open('x') as f:json.dump(out,f,indent=2);f.write('\n')
    with (folder/'registry-receipts.jsonl').open('a') as f:json.dump({'event_id':key,'sha256':digest(path.read_bytes()),'registered_at':out['registered_at']},f);f.write('\n')
    return out


def evaluate_registered(folder, finals, artifact_path):
    """Read-only paired research settlement, with frozen evaluation horizon."""
    data=Path(artifact_path).read_bytes();model=json.loads(data);result=[];now=datetime.now(timezone.utc)
    if digest(Path(model['protocol_path']).read_bytes())!=model['protocol_sha256']:raise ValueError('frozen protocol changed')
    journal=Path(folder)/'registry-receipts.jsonl'
    entries=[json.loads(s) for s in journal.read_text().splitlines()] if journal.exists() else []
    if len(entries)!=len({r['event_id'] for r in entries}):raise ValueError('duplicate registry receipt')
    expected={r['event_id']:r['sha256'] for r in entries}
    paths=sorted(Path(folder).glob('*.json'))
    if set(expected)!=set(path.stem for path in paths):raise ValueError('registry files deleted, copied or missing receipts')
    if digest(Path(__file__).read_bytes())!=model['feature_code_sha256']:raise ValueError('candidate feature code changed after freeze')
    seen=set()
    for path in paths:
        row=json.loads(path.read_text())
        if path.stem!=row['event_id'] or row['event_id'] in seen:raise ValueError('duplicate or renamed registry event')
        seen.add(row['event_id']);final=finals.get(row['event_id'])
        if expected.get(row['event_id'])!=digest(path.read_bytes()):raise ValueError('immutable registry record changed or unreceipted')
        if not final:continue
        if not instant(model['frozen_at'])<=instant(row['cutoff'])<=instant(row['registered_at'])<instant(row['kickoff']):raise ValueError('invalid frozen/source/registration chronology')
        for source in row['sources']:verify_snapshot(source,instant(row['cutoff']))
        if row['candidate_sha256']!=digest(data) or row['record_kind']!='PROSPECTIVE_RESEARCH_ONLY' or instant(row['registered_at'])>=instant(row['kickoff']):raise ValueError('invalid prospective record')
        if any(row[k]!=final[k] for k in ['event_id','home_id','away_id','kickoff']):raise ValueError('final identity mismatch')
        if not final.get('final') or not instant(row['kickoff'])<instant(final['observed_at'])<=now:raise ValueError('unverified final')
        verify_snapshot(final['source'],now)
        if any(type(final[k]) is not int or final[k]<0 for k in ['home_score','away_score']):raise ValueError('invalid final score')
        margin=final['home_score']-final['away_score'];errors={label:abs(margin-row[field]) for label,field in [('baseline','baseline_expected_home_margin'),('shadow','shadow_expected_home_margin'),('selected','selected_research_expected_home_margin'),('train_mean','train_mean_expected_home_margin'),('train_median','train_median_expected_home_margin')]}
        result.append({'event_id':row['event_id'],'week':row['week'],'season':row['season'],'season_type':row['season_type'],'nonzero_shock':any(row['features'][g]!=0 for g in GROUPS),'absolute_errors':errors,'source_record_sha256':digest(path.read_bytes())})
    thresholds=model['prospective_thresholds'];weeks=len({(r['season'],r['season_type'],r['week']) for r in result});exposures=sum(r['nonzero_shock'] for r in result)
    ready=len(result)>=thresholds['min_games'] and exposures>=thresholds['min_nonzero_shock_games'] and weeks>=thresholds['min_week_blocks']
    return {'settled_games':len(result),'resolved_nonzero_shock_games':exposures,'week_blocks':weeks,'predeclared_sample_horizon_reached':ready,'independent_source_authentication':False,'production_approved':False,'results':result}
