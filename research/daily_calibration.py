"""Frozen research categorical calibration; shared joint-score support only."""
import hashlib
import json
import math
from datetime import datetime
import numpy as np
from scipy.optimize import minimize

RIDGE=10.0
SPORTS=('NCAAF','NFL','NCAAB')


def _time(x):
    t=datetime.fromisoformat(x.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('aware timestamp required')
    return t


def category(margin,sport):
    if sport not in SPORTS or not math.isfinite(margin) or margin!=int(margin):raise ValueError('integer margin and supported sport required')
    if sport=='NFL':return {0:0,-7:1,-3:2,3:3,7:4}.get(margin,5)
    if sport=='NCAAF':
        if margin==0:raise ValueError('NCAAF final score cannot tie')
        return {-7:0,-3:1,3:2,7:3}.get(margin,4)
    if margin==0:raise ValueError('NCAAB final score cannot tie')
    magnitude=0 if abs(margin)<=3 else 1 if abs(margin)<=10 else 2
    return magnitude+(0 if margin<0 else 3)


def category_probabilities(scores,sport):
    counts=np.zeros(6 if sport in ('NFL','NCAAB') else 5)
    if not scores:raise ValueError('nonempty joint support required')
    for h,a in scores:
        if not all(math.isfinite(x) and x>=0 and x==int(x) for x in (h,a)):raise ValueError('nonnegative integer scores required')
        counts[category(h-a,sport)]+=1
    return (counts/counts.sum()).tolist()


def fit(rows,sport,fit_cutoff):
    """Fit fixed ridge tilt against EACH game's forecast probabilities.

    Row: event_id,kickoff,result_observed_at,forecast_category_probabilities,
    actual_margin. No test rows or source timestamps after fit_cutoff accepted.
    Original publication authenticity must be established independently.
    """
    if sport not in SPORTS:raise ValueError('unsupported sport')
    cutoff=_time(fit_cutoff);rows=list(rows);seen=set();probs=[];truth=[]
    for r in rows:
        if r['event_id'] in seen:raise ValueError('duplicate event')
        seen.add(r['event_id'])
        if not _time(r['kickoff'])<_time(r['result_observed_at'])<=cutoff:raise ValueError('future or unavailable result')
        p=np.asarray(r['forecast_category_probabilities'],dtype=float);k=6 if sport in ('NFL','NCAAB') else 5
        if p.shape!=(k,) or not np.isfinite(p).all() or (p<0).any() or not np.isclose(p.sum(),1,atol=1e-10):raise ValueError('normalized forecast category probabilities required')
        y=category(r['actual_margin'],sport)
        if p[y]<=0:raise ValueError('observed category outside forecast support')
        probs.append(p);truth.append(y)
    if len(rows)<30:raise ValueError('at least30 resolved calibration games required')
    p=np.asarray(probs);y=np.asarray(truth);n,k=p.shape
    logp=np.full_like(p,-np.inf);np.log(p,out=logp,where=p>0)
    def objective(theta):
        x=logp+theta;mx=x.max(axis=1,keepdims=True);e=np.exp(x-mx);q=e/e.sum(axis=1,keepdims=True)
        loss=float((np.log(e.sum(axis=1))+mx[:,0]-x[np.arange(n),y]).sum()+RIDGE*.5*np.dot(theta,theta))
        g=q.sum(axis=0)-np.bincount(y,minlength=k)+RIDGE*theta
        return loss,g
    res=minimize(objective,np.zeros(k),jac=True,method='L-BFGS-B',options={'maxiter':500,'ftol':1e-12,'gtol':1e-8})
    if not res.success or not np.isfinite(res.x).all():raise ValueError('calibration optimizer failed: '+res.message)
    before=objective(np.zeros(k))[0];after=objective(res.x)[0]
    return {'version':'daily-joint-category-tilt-v1','sport':sport,'approval':'RESEARCH_ONLY',
      'fit_cutoff':fit_cutoff,'ridge':RIDGE,'offsets':res.x.tolist(),'n':n,
      'training_objective_before':before,'training_objective_after':after,
      'input_sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
      'source_authentication':'NOT_VERIFIED','prospective_outcomes':0,
      'fit_type':'conditional category likelihood with per-game predicted-probability offsets; fixed ridge, no grid',
      'category_definition':'signed football keys -7,-3,+3,+7, NFL tie0; NCAAB negative/positive margins1-3,4-10,11+',
      'no_support_added':True}


def apply(scores,artifact):
    """Return {'scores': same atoms, 'weights': normalized weights}.

    All markets must derive W/P/L from this same weighted distribution.
    """
    if artifact.get('version')!='daily-joint-category-tilt-v1' or artifact.get('approval')!='RESEARCH_ONLY':raise ValueError('unrecognized frozen calibration')
    sport=artifact['sport'];category_probabilities(scores,sport)
    theta=np.asarray(artifact['offsets'],dtype=float)
    expected=6 if sport in ('NFL','NCAAB') else 5
    if theta.shape!=(expected,) or not np.isfinite(theta).all():raise ValueError('invalid offsets')
    logw=np.array([theta[category(h-a,sport)] for h,a in scores]);w=np.exp(logw-logw.max());w/=w.sum()
    return {'scores':[tuple(s) for s in scores],'weights':w.tolist(),'approval':'RESEARCH_ONLY'}
