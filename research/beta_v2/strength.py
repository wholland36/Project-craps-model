"""Versioned beta strength; source-time limitations remain explicit."""
import math
from datetime import datetime,timezone
import numpy as np
from scipy.sparse import lil_matrix,vstack,diags
from scipy.sparse.linalg import lsqr
VERSION='beta-v2-strength-20261105'
def instant(x):
 t=datetime.fromisoformat(str(x).replace('Z','+00:00'))
 if t.tzinfo is None:raise ValueError('timezone required')
 return t.astimezone(timezone.utc)
def boolean(x):
 if isinstance(x,(bool,np.bool_)):return bool(x)
 if isinstance(x,str) and x.upper() in ('TRUE','FALSE'):return x.upper()=='TRUE'
 raise ValueError('explicit boolean required')
def fit(rows,*,sport,cutoff,ridge=20.,residuals=None):
 checked=[];seen=set()
 for row in rows:
  r=dict(row)
  if r['event_id'] in seen:raise ValueError('duplicate event')
  seen.add(r['event_id']);r['neutral']=boolean(r['neutral'])
  if not boolean(r.get('final',False)):continue
  if str(r['home_id'])==str(r['away_id']):raise ValueError('same participant')
  if not instant(r['kickoff'])<instant(r['result_observed_at']):raise ValueError('invalid reconstructed availability')
  for k in ('home_score','away_score'):
   if isinstance(r[k],bool) or not math.isfinite(float(r[k])) or r[k]<0:raise ValueError('invalid score')
  if sport=='NCAAB' and (not math.isfinite(float(r['possessions'])) or r['possessions']<=0 or r['minutes']<40):raise ValueError('invalid box scope')
  if instant(r['result_observed_at'])<instant(cutoff):checked.append(r)
 rows=checked
 if len(rows)<50:raise ValueError('insufficient prior games')
 teams=sorted({r[k] for r in rows for k in ('home_id','away_id')});ix={t:i for i,t in enumerate(teams)};n=len(teams)
 x=lil_matrix((len(rows)*2,2*n+2));y=[];w=[];latest=max(r['season'] for r in rows)
 for i,r in enumerate(rows):
  p=r['possessions'] if sport=='NCAAB' else 1
  for k,(t,o,s,h) in enumerate([(r['home_id'],r['away_id'],r['home_score'],True),(r['away_id'],r['home_id'],r['away_score'],False)]):
   j=2*i+k;x[j,0]=1;x[j,1+ix[t]]=1;x[j,1+n+ix[o]]=-1;x[j,-1]=float(h and not r['neutral']);y.append(s/p);w.append(.5**((latest-r['season'])/2))
 x=x.tocsr();w=np.asarray(w);xx=x.multiply(w[:,None]);scale=np.sqrt(np.asarray(xx.power(2).sum(axis=0)).ravel()/sum(w*w));scale[scale==0]=1;scale[0]=1
 # Penalize standardized team contrasts; venue has its own weak penalty.
 penalty=np.full(2*n+2,ridge);penalty[0]=0;penalty[-1]=1
 xs=xx@diags(1/scale);sol=lsqr(vstack([xs,diags(np.sqrt(penalty))]),np.r_[np.asarray(y)*w,np.zeros(2*n+2)],atol=1e-9,btol=1e-9);b=sol[0]/scale
 pace={};ot=sum((r.get('minutes',40)/40-1) for r in rows)/len(rows) if sport=='NCAAB' else 0
 for t in teams:
  rr=[r for r in rows if t in (r['home_id'],r['away_id'])]
  if sport=='NCAAB':pace[t]=sum(r['possessions']*40/r['minutes']*.5**(latest-r['season']) for r in rr)/sum(.5**(latest-r['season']) for r in rr)
 m=dict(version=VERSION,sport=sport,cutoff=cutoff,train_n=len(rows),train_last=max(r['kickoff'] for r in rows),latest_result_observed_at=max(r['result_observed_at'] for r in rows),parameters=dict(intercept=float(b[0]),home_effect=float(b[-1]),offense={t:float(b[1+i]) for t,i in ix.items()},defense={t:float(b[1+n+i]) for t,i in ix.items()}),pace=pace,ot_expected_extra_fraction=ot,ot_model='prior full-game minutes mixture mean; remaining variability in paired OOF residuals, not independent OT process',ridge=ridge,venue_ridge=1,standardization='weighted column RMS; separate venue penalty',season_retention=.5,mode='box_ppp_regulation_pace' if sport=='NCAAB' else 'opponent_adjusted_full_score_fallback_NO_DRIVE_INPUTS',residual_pairs=residuals or [],solver_istop=int(sol[1]),solver_iterations=int(sol[2]),approval='RESEARCH_ONLY',source_authentication='retrospective captures; result availability assumed 24h lag, not independently authenticated')
 return m
def point(model,event):
 h=str(event['home_id']);a=str(event['away_id']);b=model['parameters'];o=b['offense'];d=b['defense']
 if h not in o or a not in o:return None
 p=1
 if model['sport']=='NCAAB':p=(model['pace'][h]+model['pace'][a])/2*(1+model['ot_expected_extra_fraction'])
 return [max(0,(b['intercept']+o[h]-d[a]+(0 if event['neutral'] else b['home_effect']))*p),max(0,(b['intercept']+o[a]-d[h])*p)]
def predict(model,event):
 if instant(event['kickoff'])<=instant(model['cutoff']):raise ValueError('forecast must follow cutoff')
 event=dict(event);event['neutral']=boolean(event['neutral']);p=point(model,event)
 if p is None:return {'status':'UNSEEN_TEAM'}
 if not model['residual_pairs']:return {'status':'NO_PRIOR_RESIDUALS','point_scores':p}
 scores=[[max(0,round(p[0]+h)),max(0,round(p[1]+a))] for h,a in model['residual_pairs']]
 if model['sport']=='NCAAB':scores=[s for s in scores if s[0]!=s[1]]
 return dict(status='RESEARCH_ONLY',point_scores=p,paired_score_samples=scores,distribution_center_scores=np.mean(scores,axis=0).tolist(),production_approved=False)
