"""Additive source-conflict quarantine and exact-result grading for focus shadows."""
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path
from . import ncaaf_focus as focus
from .ncaaf_next import sha,canonical,exclusive,capture
from .market_audit import settlement
QUARANTINE={'401862818':{'reason':'official_USF_19_30_ET_vs_ESPN_20_30_ET_kickoff_conflict','official_source':'https://gousfbulls.com/news/2026/11/6/football-keys-to-the-game-bulls-vs-pirates','official_kickoff':'2026-11-06T23:30:00+00:00','preserved_ESPN_kickoff':'2026-11-07T00:30:00+00:00'}}
def eligible_identity(row,data):
 gid=str(data.get('header',{}).get('id'))
 if gid in QUARANTINE:return False
 cs=data.get('header',{}).get('competitions',[])
 if len(cs)!=1:return False
 c=cs[0];teams={t['homeAway']:t for t in c.get('competitors',[])}
 return gid==row['event_id'] and set(teams)=={'home','away'} and all(str(teams[s]['team']['id'])==row[s+'_id'] for s in teams) and focus.beta_daily.instant(c['date'])==focus.beta_daily.instant(row['kickoff'])
def run(output):
 guard=json.loads((focus.ROOT/'guard-manifest.json').read_text())
 if guard['code_sha256']!=sha(Path(__file__).read_bytes()) or guard['quarantine_sha256']!=sha(canonical(QUARANTINE)):raise ValueError('guard drift')
 # Do not edit the original focus code, predictions, or model freeze.
 focus.IDS=[i for i in focus.IDS if i not in QUARANTINE];result=focus.run(output)
 now=datetime.now(timezone.utc);newgrades=0;revision=[]
 for runpath in sorted((focus.ROOT/'runs').glob('*.json')):
  payload=json.loads(runpath.read_text())
  for row in payload['rows']:
   if row['event_id'] in QUARANTINE or focus.beta_daily.instant(row['kickoff'])>=now:continue
   rec,data=capture(focus.BASE+'/summary?event='+row['event_id'],focus.ROOT,now)
   if data is None or not eligible_identity(row,data):revision.append(row['event_id']);continue
   c=data['header']['competitions'][0]
   if not c['status']['type'].get('completed'):continue
   ts={t['homeAway']:t for t in c['competitors']};hs=int(ts['home']['score']);aws=int(ts['away']['score'])
   q=dict(row,home_score=hs,away_score=aws);outcome=settlement(q);p=[row['p_win'],row['p_push'],row['p_loss']];ix={1:0,0:1,-1:2}[outcome]
   key=sha(canonical(row));path=focus.ROOT/'grades'/(key+'.json')
   if path.exists():
    prior=json.loads(path.read_text())
    if [prior['home_score'],prior['away_score']]!=[hs,aws]:revision.append(row['event_id'])
    continue
   grade=dict(event_id=row['event_id'],forecast_sha256=key,variant=row['variant'],market=row['market'],home_score=hs,away_score=aws,observed_at=rec['observed_at'],result_source_sha256=rec['sha256'],wpl_brier=sum((v-int(j==ix))**2 for j,v in enumerate(p)),logloss=None if p[ix]==0 else -math.log(p[ix]),infinite_logloss=p[ix]==0,conditional_brier=(p[0]/(p[0]+p[2])-int(outcome==1))**2 if outcome and p[0]+p[2]>0 else None,hypothetical_profit=focus.odds_profit(row['american_odds']) if outcome==1 else -1 if outcome==-1 else 0,quote_authenticated=False,official_pnl=0,cohort='REFERENCE_ONLY_EXPLORATORY; repeated snapshots/complements not independent games')
   exclusive(path,canonical(grade));newgrades+=1
 result.update(quarantines=QUARANTINE,new_shadow_grades=newgrades,result_revision_events=sorted(set(revision)),quarantined_prior_rows_preserved=True)
 (output/'FIVE_GAME_STATUS.json').write_text(json.dumps(result,indent=2)+'\n')
 with (output/'FIVE_GAME_REPORT.md').open('a') as f:
  f.write('\n## Source conflict quarantine\n\nSouth Florida–East Carolina (401862818) is excluded from new shadow inference and grading: official USF preview gives 7:30 p.m. Eastern, while preserved ESPN/forecast gives 8:30 p.m. Eastern. Prior 50-row snapshot remains intact and that event is ineligible for evaluation until independently reconciled. Four other events continue reference-only tracking.\n\n'+f'New exact-identity shadow grades this run: {newgrades}. Result revisions: {sorted(set(revision))}. Repeated source snapshots, complementary selections and variants are not independent samples. No executable-price ROI or CLV is certified.\n')
 return {k:v for k,v in result.items() if k!='events'}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(run(a.output),indent=2))
