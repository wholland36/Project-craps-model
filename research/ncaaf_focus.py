"""Separate five-game reference-price shadow bridge; no official forecast edits."""
import argparse,json,math,hashlib
from datetime import datetime,timezone
from pathlib import Path
from .ncaaf_next import capture,canonical,exclusive,sha,STUDY
from . import beta_daily
from .beta_v2.daily_entry import check_entry
from .beta_v2.runtime import load_bundle,STATE
from project_craps.model import outcome_masses
from research.market_audit import implied,odds_profit
ROOT=beta_daily.CENTRAL/'state/research-extensions/ncaaf-focus-20261106'
IDS=['401858288','401862818','401858510','401864533','401856855']
BASE='https://site.api.espn.com/apis/site/v2/sports/football/college-football'
def pair_masses(p,intercept,slope):
 if slope<0:raise ValueError('negative slope violates ordered spread probabilities')
 w,push,l=map(float,p)
 if min(w,push,l)<0 or abs(w+push+l-1)>1e-10:raise ValueError('invalid WPL')
 if w+l<=0:raise ValueError('no conditional support')
 c=w/(w+l)
 if c==0 or c==1:
  cnew=c if slope>0 else 1/(1+math.exp(-intercept))
 else:cnew=1/(1+math.exp(-(intercept+slope*math.log(c/(1-c)))))
 return [cnew*(1-push),push,(1-cnew)*(1-push)]
def blend(p,market):
 w,push,l=p;c=.5*w/(w+l)+.5*market
 return [c*(1-push),push,(1-c)*(1-push)]
def reference_pairs(data,event):
 pairs=[]
 for book in data.get('pickcenter',[]):
  h=book.get('homeTeamOdds',{});a=book.get('awayTeamOdds',{})
  if str(h.get('teamId'))!=event['home_id'] or str(a.get('teamId'))!=event['away_id']:continue
  for market,side,line,left,right in [('moneyline','home',None,h.get('moneyLine'),a.get('moneyLine')),('spread','home',book.get('spread'),h.get('spreadOdds'),a.get('spreadOdds')),('total','over',book.get('overUnder'),book.get('overOdds'),book.get('underOdds'))]:
   if left is None or right is None or (market!='moneyline' and line is None):continue
   odds_profit(left);odds_profit(right)
   pairs.append(dict(market=market,selection=side,line=line,american_odds=left,opposing_american_odds=right,book=book['provider']['name'],book_id=str(book['provider']['id']),source='ESPN pickcenter attribution',original_quote_time=None,independently_authenticated=False,scope='full_game_including_overtime_ASSUMPTION',reference_only=True))
 return pairs

def run(output):
 check_entry();load_bundle(STATE);pointer,runtime=beta_daily.official_check();now=datetime.now(timezone.utc)
 art=json.loads((ROOT/'challengers.json').read_text());manifest=json.loads((ROOT/'manifest.json').read_text())
 if sha((ROOT/'challengers.json').read_bytes())!=manifest['artifact_sha256'] or sha(Path(__file__).read_bytes())!=manifest['code_sha256']:raise ValueError('focus frozen code/artifact drift')
 model_path=Path(pointer['sports']['NCAAF']['path']);wrapper=json.loads(model_path.read_text());model=wrapper.get('payload',wrapper)
 if sha(model_path.read_bytes())!=art['parent_model_sha256']:raise ValueError('parent model drift')
 allrows=[];sources=[];events=[]
 for gid in IDS:
  rec,data=capture(BASE+'/summary?event='+gid,ROOT,now);sources.append(rec)
  if not data:events.append(dict(event_id=gid,status='SOURCE_UNAVAILABLE'));continue
  competitions=data.get('header',{}).get('competitions',[])
  if len(competitions)!=1:raise ValueError('ambiguous event')
  c=competitions[0];sides={t['homeAway']:t for t in c['competitors']};e=dict(event_id=gid,home_id=str(sides['home']['team']['id']),away_id=str(sides['away']['team']['id']),kickoff=c['date'])
  if str(data['header']['id'])!=gid:raise ValueError('event identity mismatch')
  if beta_daily.instant(e['kickoff'])<=now or c['status']['type'].get('state')!='pre':continue
  paths=list(Path(runtime['first_forecast_registry']).glob('NCAAF-'+gid+'-*.json'))
  if len(paths)!=1:raise ValueError('ambiguous parent forecast')
  ref=json.loads(paths[0].read_text())
  if ref['record_sha256']!=beta_daily.reference_digest(ref):raise ValueError('parent forecast digest mismatch')
  if any(str(ref[k])!=e[k] for k in ['home_id','away_id']) or beta_daily.instant(ref['kickoff'])!=beta_daily.instant(e['kickoff']):raise ValueError('identity/kickoff revision quarantined')
  if ref['model_sha256']!=art['parent_model_sha256'] or beta_daily.instant(ref['issued_at'])>=now:raise ValueError('parent/time mismatch')
  scores=beta_daily.reference_scores(ref,model)
  for q in reference_pairs(data,e):
   mass=list(outcome_masses(scores,q['market'],q['selection'],q['line'],tie_policy='refund' if q['market']=='moneyline' else None))
   pn=implied(q['american_odds'])/(implied(q['american_odds'])+implied(q['opposing_american_odds']))
   variants={'baseline_point_kernel':mass}
   if q['market']=='spread':variants['bounded_spread_recalibration']=pair_masses(mass,art['spread']['intercept'],art['spread']['slope'])
   if q['market']=='total':variants['fixed_total_market_blend']=blend(mass,pn)
   for name,p in variants.items():
    row=dict(q,event_id=gid,home_id=e['home_id'],away_id=e['away_id'],kickoff=e['kickoff'],observed_at=rec['observed_at'],issued_at=datetime.now(timezone.utc).isoformat(),source_sha256=rec['sha256'],parent_first_forecast_sha256=ref['record_sha256'],parent_feature_cutoff=ref['feature_cutoff'],model_artifact_sha256=manifest['artifact_sha256'],variant=name,p_win=p[0],p_push=p[1],p_loss=p[2],no_vig_conditional=pn,research_only=True,approved_risk=0,decision='PASS: reference price only; roster/weather incomplete; historical feature cutoff retained',cohort='EXPLORATORY_FORWARD_SHADOW_NOT_CONFIRMATION',quote_publication_authentication=False,parent_reconstruction='new point-kernel calculation from frozen first means; not original betting probability')
    # Side-complement rows use same pair and preserve push exactly.
    other=dict(row,selection='away' if q['selection']=='home' else 'under',line=-q['line'] if q['market']=='spread' else q['line'],american_odds=q['opposing_american_odds'],opposing_american_odds=q['american_odds'],p_win=p[2],p_loss=p[0],no_vig_conditional=1-pn)
    allrows.extend([row,other])
  events.append(dict(event_id=gid,home=sides['home']['team']['displayName'],away=sides['away']['team']['displayName'],kickoff=e['kickoff'],weather_candidate=data.get('gameInfo',{}).get('weather'),weather_original_publication=None,injuries_endpoint_empty_is_not_clearance=not bool(data.get('injuries')),betting_supported=False,missing=['complete game-day QB/injury/replacement allocation','authenticated Hard Rock Florida pair and original update time','validated date-aware feature freshness','authenticated weather publication/cutoff'],approved_risk=0))
 stamp=now.strftime('%Y%m%dT%H%M%S%fZ');payload=dict(asof=now.isoformat(),events=events,rows=allrows,sources=sources,approved_risk=0,paid_requests=0)
 exclusive(ROOT/'runs'/(stamp+'.json'),canonical(payload))
 output.mkdir(parents=True,exist_ok=True)
 # User-facing output avoids numerical unvalidated probabilities; private records retain them.
 public=dict(asof=now.isoformat(),events=events,reference_quote_selections=sum(r['variant']=='baseline_point_kernel' for r in allrows),shadow_predictions=len(allrows),authenticated_executable_quotes=0,approved_risk=0,challenger_artifact_sha256=manifest['artifact_sha256'],rejected_unconstrained_spread_slope=art['rejected_unconstrained_spread_slope'],pilot_confirmation_eligible=False)
 (output/'FIVE_GAME_STATUS.json').write_text(json.dumps(public,indent=2)+'\n')
 (output/'FIVE_GAME_REPORT.md').write_text('# Five-game NCAA football shadow check\n\nResearch only; approved risk $0.\n\n'+f"Captured {len(events)} event summaries, {public['reference_quote_selections']} baseline market/selection records and {len(allrows)} total shadow records. Paired prices are attributed to DraftKings by ESPN; original quote times and Hard Rock Florida offers are unverified. Values remain private and are not betting recommendations.\n\n"+'|Game|Kickoff UTC|Decision|\n|---|---|---|\n'+'\n'.join(f"|{e.get('away','')} at {e.get('home','')}|{e.get('kickoff','')}|PASS: required evidence incomplete|" for e in events)+'\n\nUnconstrained historical spread calibration was rejected: negative slope reverses ordered cover probabilities. Separate nonnegative-slope calibration is frozen, and the fixed 50/50 total blend is explicitly market-informed. Both are exploratory forward shadows; no confirmation has started.\n\nOfficial first forecasts and their old feature cutoffs remain intact; new calculations are timestamped now. Current roster and weather are not silently treated as model inputs.\n')
 return public
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args();print(json.dumps(run(a.output),indent=2))
