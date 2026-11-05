"""Parent-bound, train-only joint categorical calibration; research only.

No synthetic inputs, market-wise clipping, or transported v1 offsets. All
markets are projections of one nonnegative integer joint-score distribution.
"""
import hashlib
import json
import math
from datetime import datetime
import numpy as np
from scipy.optimize import minimize

VERSION='beta-v2-parent-bound-joint-calibration-v1'
RIDGE=50.0
SCHEMA='integer-home-away-atoms; NFL-final-includes-ties; NCAAB-final-excludes-ties'

def _time(x):
    t=datetime.fromisoformat(x.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('aware timestamp required')
    return t

def _digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def _atoms(scores,sport):
    a=np.asarray(scores,dtype=float)
    if a.ndim!=2 or a.shape[1]!=2 or not len(a) or not np.isfinite(a).all() or (a<0).any() or (a!=np.floor(a)).any(): raise ValueError('finite nonnegative integer joint atoms required')
    if sport not in ('NFL','NCAAB'): raise ValueError('unsupported sport')
    if sport=='NCAAB' and np.any(a[:,0]==a[:,1]): raise ValueError('NCAAB final ties prohibited')
    return a

def _category(m,t,pt,sport):
    if sport=='NFL': k={0:0,-7:1,-3:2,3:3,7:4}.get(int(m),5)
    else: k=(0 if abs(m)<=3 else 1 if abs(m)<=10 else 2)+(0 if m<0 else 3)
    tb=0 if t<pt-10 else 2 if t>pt+10 else 1
    return k*3+tb

def _design(a,meta,sport):
    pm=float(meta['predicted_margin']);pt=float(meta['predicted_total'])
    if not math.isfinite(pm) or not math.isfinite(pt): raise ValueError('finite parent predictions required')
    m=a[:,0]-a[:,1];t=a.sum(axis=1)
    cats=np.array([_category(x,y,pt,sport) for x,y in zip(m,t)])
    # Fixed broad strength regime; no optimized cut points or metadata imputation.
    regime=int(abs(pm)>7)
    x=np.eye(18)[cats]
    if sport=='NFL': x=np.concatenate([x,np.eye(6)[cats//3]*regime],axis=1)
    return x,cats

def fit(rows,sport,fit_cutoff,parent,minimum_games=30):
    """Rows must be earlier OOF parent predictions, never parent in-sample rows.

    Parent binding requires model_sha256, version, and schema. The caller must
    attest OOF training cutoff; each row is independently checked chronologically.
    Result publication authentication is reported separately, never inferred.
    """
    if not all(parent.get(k) for k in ('model_sha256','version','schema')): raise ValueError('parent binding required')
    rows=list(rows);seen=set();valid=[];failures=[];cut=_time(fit_cutoff)
    for r in rows:
        if r['event_id'] in seen: raise ValueError('duplicate event')
        seen.add(r['event_id'])
        if r.get('sport',sport)!=sport: raise ValueError('sport mismatch')
        if parent.get('family') and r.get('parent_family')!=parent['family']: raise ValueError('OOF parent family mismatch')
        if parent.get('code_sha256') and r.get('parent_code_sha256')!=parent['code_sha256']: raise ValueError('OOF parent code mismatch')
        if not _time(r['parent_train_cutoff'])<_time(r['kickoff'])<_time(r['result_observed_at'])<=cut: raise ValueError('nonchronological OOF row')
        a=_atoms(r['scores'],sport);x,c=_design(a,r,sport)
        h=r['home_score'];aw=r['away_score']
        _atoms([[h,aw]],sport)
        actual=_category(h-aw,h+aw,r['predicted_total'],sport);mask=c==actual
        if not mask.any(): failures.append({'event_id':r['event_id'],'actual_category':actual,'reason':'zero_parent_category_support'});continue
        valid.append((x,mask))
    if len(valid)<minimum_games: raise ValueError('insufficient supported earlier OOF games: '+str(len(valid)))
    npar=valid[0][0].shape[1]
    def obj(theta):
        loss=RIDGE*.5*np.dot(theta,theta);g=RIDGE*theta.copy()
        for x,mask in valid:
            z=x@theta;z-=z.max();w=np.exp(z);q=w/w.sum();hit=w[mask].sum()
            loss+=math.log(w.sum())-math.log(hit)
            g+=q@x-(w[mask]/hit)@x[mask]
        return float(loss),g
    opt=minimize(obj,np.zeros(npar),jac=True,method='L-BFGS-B',options={'maxiter':250,'ftol':1e-10})
    if not opt.success: raise ValueError('optimizer failure: '+str(opt.message))
    return dict(version=VERSION,sport=sport,approval='RESEARCH_ONLY',parent=parent,schema=SCHEMA,fit_cutoff=fit_cutoff,ridge=RIDGE,theta=opt.x.tolist(),input_sha256=_digest(rows),rows=len(rows),supported_fit_games=len(valid),support_failures=failures,training_penalized_objective_before=obj(np.zeros(npar))[0],training_penalized_objective_after=obj(opt.x)[0],source_authentication='NOT_INFERRED',future_confirmation_games=0,tail_component='NONE; zero-support events explicitly retained as failures',optional_input_hooks={'regulation_pace':'BLOCKED unless observed timestamped input and predeclared parent feature','three_point_attempt_rate':'BLOCKED unless observed timestamped input and predeclared parent feature','late_foul':'BLOCKED until pregame causal predictor validated','overtime':'parent final-score distribution; no invented adjustment'})

def apply(scores,artifact,event_metadata):
    if artifact.get('version')!=VERSION or artifact.get('approval')!='RESEARCH_ONLY': raise ValueError('unknown calibration')
    for k in ('model_sha256','version','schema'):
        if event_metadata.get('parent',{}).get(k)!=artifact['parent'][k]: raise ValueError('parent binding mismatch: '+k)
    a=_atoms(scores,artifact['sport']);x,_=_design(a,event_metadata,artifact['sport']);theta=np.asarray(artifact['theta'],dtype=float)
    if theta.shape!=(x.shape[1],) or not np.isfinite(theta).all(): raise ValueError('invalid coefficients')
    z=x@theta;w=np.exp(z-z.max());w/=w.sum()
    return dict(scores=a.astype(int).tolist(),weights=w.tolist(),approval='RESEARCH_ONLY',parent=artifact['parent'])

def proper_scores(masses,outcome):
    """W/P/L masses and outcome index0/1/2; infinity remains explicit."""
    p=np.asarray(masses,dtype=float)
    if p.shape!=(3,) or not np.isfinite(p).all() or (p<0).any() or not np.isclose(p.sum(),1): raise ValueError('W/P/L probability vector required')
    if outcome not in (0,1,2): raise ValueError('W/P/L outcome index required')
    y=np.eye(3)[outcome];ll=-math.log(p[outcome]) if p[outcome]>0 else None
    q=p[0]/(p[0]+p[2]) if p[0]+p[2]>0 else None
    return dict(threeway_brier=float(np.sum((p-y)**2)),threeway_logloss=ll,logloss_is_infinite=ll is None,zero_probability_observed=bool(p[outcome]==0),conditional_brier=None if outcome==1 or q is None else (q-int(outcome==0))**2)

def evaluate(rows,artifact):
    """Development-only paired audit including zero-support/infinite-loss counts.

    Fixed diagnostic lines are parent-centered, not executable tickets. No ROI.
    All supplied rows must occur after fit cutoff. Actual pregame book lines may
    be supplied as evaluation_lines; their provenance is caller responsibility.
    """
    records=[]
    for r in rows:
        if _time(r['kickoff'])<=_time(artifact['fit_cutoff']): raise ValueError('evaluation overlaps fit')
        scores=_atoms(r['scores'],artifact['sport']);q=apply(r['scores'],artifact,dict(r,parent=artifact['parent']))['weights'];p=np.ones(len(scores))/len(scores)
        margin=scores[:,0]-scores[:,1];total=scores.sum(axis=1);am=r['home_score']-r['away_score'];at=r['home_score']+r['away_score']
        lines=r.get('evaluation_lines',[{'market':'moneyline','line':0},{'market':'spread','line':-round(r['predicted_margin']*2)/2},{'market':'total','line':round(r['predicted_total']*2)/2}])
        for line in lines:
            market=line['market'];v=margin if market=='moneyline' else margin+line['line'] if market=='spread' else total-line['line'];y=am if market=='moneyline' else am+line['line'] if market=='spread' else at-line['line'];truth=0 if y>0 else 2 if y<0 else 1
            rec=dict(event_id=r['event_id'],kickoff=r['kickoff'],market=market,line=line['line'],observed_outcome=truth)
            for name,w in [('raw_parent',p),('calibrated',np.array(q))]:
                masses=[float(w[v>0].sum()),float(w[v==0].sum()),float(w[v<0].sum())];rec[name]=proper_scores(masses,truth)
            records.append(rec)
    summary={}
    for market in ('moneyline','spread','total'):
        rr=[r for r in records if r['market']==market];s={}
        for name in ('raw_parent','calibrated'):
            metrics=[r[name] for r in rr];inf=sum(m['logloss_is_infinite'] for m in metrics)
            s[name]={'n':len(metrics),'threeway_brier':float(np.mean([m['threeway_brier'] for m in metrics])) if metrics else None,'infinite_logloss_count':inf,'threeway_mean_logloss':None if inf or not metrics else float(np.mean([m['threeway_logloss'] for m in metrics])),'logloss_mean_is_infinite':bool(inf),'conditional_brier':float(np.mean([m['conditional_brier'] for m in metrics if m['conditional_brier'] is not None])) if any(m['conditional_brier'] is not None for m in metrics) else None}
        blocks={}
        for rec in rr:
            dt=_time(rec['kickoff']);key=tuple(dt.isocalendar()[:2])
            blocks.setdefault(key,[]).append(rec['calibrated']['threeway_brier']-rec['raw_parent']['threeway_brier'])
        rng=np.random.RandomState(20261105);bb=list(blocks.values());boot=[]
        if len(bb)>=2:
            for _ in range(2000):
                picked=[bb[i] for i in rng.randint(0,len(bb),len(bb))];boot.append(sum(sum(v) for v in picked)/sum(len(v) for v in picked))
        s['paired_brier_delta']={'calibrated_minus_parent':float(np.mean([v for block in bb for v in block])) if bb else None,'week_blocks':len(bb),'week_bootstrap_95_ci':np.percentile(boot,[2.5,97.5]).tolist() if boot else None,'interpretation':'development descriptive, multiple inspected endpoints; not prospective approval'}
        summary[market]=s
    return dict(status='HISTORICAL_DEVELOPMENT_ALREADY_INSPECTED_NOT_FRESH_CONFIRMATION',markets=summary,observations=records,roi=None,roi_reason='Diagnostic parent-centered thresholds are not authenticated executable tickets',remaining_transport_risk='Same-family OOF calibrator applied to newly estimated parent weights; prospective confirmation required')

def build(state,output,deployment_cutoff=None):
    """Refit deployment on ALL eligible earlier OOF rows, no tuning.

    Preserve the historical development fit separately. Caller supplies a private
    experiment directory. Must run before registering forecasts against this
    artifact; subsequent forecasts bind its bytes. Never rewrites a different
    existing deployment artifact: updates belong in a new versioned state.
    """
    from pathlib import Path
    from datetime import timezone
    state=Path(state);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    cutoff=deployment_cutoff or datetime.now(timezone.utc).isoformat();_time(cutoff)
    if _time(cutoff)>datetime.now(timezone.utc): raise ValueError('future deployment cutoff prohibited')
    (state/'calibration-development').mkdir(exist_ok=True);(state/'calibration').mkdir(exist_ok=True)
    summaries={}
    for sport in ('NFL','NCAAB'):
        pp=state/'strength'/(sport+'.json');raw=pp.read_bytes();model=json.loads(raw)
        rp=state/'data'/(sport+'-oof.json');rows=json.loads(rp.read_bytes())
        parent=dict(model_sha256=hashlib.sha256(raw).hexdigest(),version=model['version'],schema=SCHEMA,family='beta-v2-strength-20261105',code_sha256=model['code_sha256'])
        eligible=[r for r in rows if _time(r['result_observed_at'])<=_time(cutoff)]
        target=state/'calibration'/(sport+'.json');development=state/'calibration-development'/(sport+'.json')
        # Preserve original pre-2026 fit once, before a full-data final refit.
        if target.exists() and not development.exists():
            old=json.loads(target.read_bytes())
            if not old.get('deployment_refit_all_earlier_oof',False):
                with development.open('xb') as f:f.write(target.read_bytes())
                development.chmod(0o600)
        a=fit(eligible,sport,cutoff,parent)
        a.update(deployment_refit_all_earlier_oof=True,source_data_sha256=hashlib.sha256(rp.read_bytes()).hexdigest(),availability_time_basis='RECONSTRUCTED_24H_EMBARGO_NOT_ORIGINAL_OBSERVATION',historical_development_already_inspected=True,remaining_transport_risk='Same-family OOF and final-parent parameters differ; future independent confirmation required',calibration_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        payload=(json.dumps(a,indent=2,allow_nan=False)+'\n').encode()
        if target.exists():
            prior=json.loads(target.read_bytes())
            if prior.get('deployment_refit_all_earlier_oof',False):
                # Same source, parent and code is a reproducible daily no-op.
                if all(prior.get(k)==a.get(k) for k in ('source_data_sha256','parent','calibration_code_sha256')):
                    a=prior;payload=target.read_bytes()
                else: raise ValueError('deployment calibration immutable; use a new versioned state')
            else:
                if not development.exists() or target.read_bytes()!=development.read_bytes(): raise ValueError('cannot replace unpreserved development fit')
                target.unlink()
        if not target.exists():
            with target.open('xb') as f:f.write(payload)
            target.chmod(0o600)
        summaries[sport]=dict(deployment_fit_games=a['rows'],supported_fit_games=a['supported_fit_games'],support_failure_games=len(a['support_failures']),ineligible_future_or_unavailable=len(rows)-len(eligible),fit_cutoff=a['fit_cutoff'],artifact_sha256=hashlib.sha256(payload).hexdigest(),parent=a['parent'],development_fit_games=json.loads(development.read_bytes())['rows'] if development.exists() else None,prospective_validation_games=0)
    (output/'deployment-refit-report.json').write_text(json.dumps(summaries,indent=2)+'\n')
    return summaries
