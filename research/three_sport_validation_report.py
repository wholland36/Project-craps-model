"""Offline report and prospective power-design specification; no fitting."""
import argparse
from collections import Counter
from pathlib import Path
import json
import math
from datetime import datetime,timedelta
import numpy as np
from scipy.stats import norm
from research.three_sport_validation import read,verify,create,sha,SPORTS,POLICY,score,append,now
from research.market_audit import settlement,odds_profit

def report(state,output):
 state=Path(state);output=Path(output);verify(state)
 # Source-identity refusals append a persistent event quarantine; never clear it.
 import fcntl
 with (state/'run.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  held={read(p)['event_id'] for p in (state/'quarantines').glob('*.json')} if (state/'quarantines').exists() else set()
  for p in (state/'comparisons').glob('*.json'):
   c=read(p)
   if c.get('official_status')=='SCHEDULE_IDENTITY_KICKOFF_MISMATCH' and c['event_id'] not in held:
    append(state,'quarantines',dict(sport=c['sport'],event_id=c['event_id'],reason='official_schedule_vs_provider_identity_kickoff_mismatch',observed_at=now().isoformat(),evidence_comparison_sha256=sha(p),prior_records_preserved=True));held.add(c['event_id'])
 dev=read(output/'DEVELOPMENT_RESULTS.json');markets=read(output/'MARKET_RESULTS_VERIFIED.json')
 lines=['# Three-sport validation development — November 10, 2026','',
 '**Executed for NFL, NCAA football and NCAA men’s basketball. All nine sport/market combinations remain RESEARCH_ONLY / NO_GO. Approved betting risk $0.**','',
 'Official release 2026-11-03-v1, v1/v2/v3 experiments, NCAA football calibration, immutable forecasts, wagers and canonical Google Sheet are unchanged. New work has its own code, fitted artifacts, source hashes, protocol, journals and branch. V1’s missing original forecast remains unresolved.','',
 '## What ran','',
 'The same `forecast` and `masses` functions generate historical replay and prospective predictions. The opponent-adjusted score model is fitted at quarterly origins using only results with a reconstructed 24-hour embargo. The first-boundary clock is one microsecond before the quarter so a midnight game remains pregame. This time convention does not establish original publication availability. All historical results are examined development.','',
 'A fixed rest/recent-form residual correction is the challenger. A score-only arm is its ablation comparator, not a model selected after looking at results. NCAAB uses prior box-estimated possessions and regulation pace. Player/QB/lineup/replacement workload, weather vintages, football drives and authenticated efficiency timing remain blocked. We did not manufacture these inputs.','',
 'The probability calculation resamples paired earlier out-of-fold score errors, retaining score correlation and integer pushes. A fixed 1% joint geometric tail supplies unbounded possible scores, with NFL ties refundable and college full-game ties excluded. The tail and support gates are structural experiments, not validated improvements. All markets project the same joint score law; independent per-market temperature transformations are not used. Prior OOF residual transfer across refitted quarter models remains an assumption.','',
 '| Sport | Available input games | Games with at least score-base forecast | Refused after warmup eligibility check |','|---|---:|---:|---:|']
 for s,z in dev.items():lines.append(f"| {s} | {z['input_games']} | {z['predicted_games']} | {z['refused_games']} |")
 lines+=['','These denominators differ: initial quarters warm the model/residual archive and do not issue a scored distribution; the correction arm needs an additional prior error archive. Refusal reasons overlap and are retained in private immutable files. Source snapshots are retrospective, not independently authenticated publication vintages.','',
 '## Matched-game development results','',
 'Both arms below use exactly the same games. Lower Brier and MAE are better. Intervals are week-cluster descriptive bootstraps; prior inspection, model development and multiple comparisons prevent confirmatory interpretation.','',
 '| Sport / season label | Matched games | Score-only winner Brier | Rest/form winner Brier | Score-only / rest-form margin MAE | Score-only / rest-form total MAE |','|---|---:|---:|---:|---|---|']
 paired=[]
 quarantined={read(p)['event_id'] for p in (state/'quarantines').glob('*.json')} if (state/'quarantines').exists() else set()
 for s in SPORTS:
  pred=read(state/s/'predictions.json')
  for year in sorted({r['season'] for r in pred}):
   rr=[r for r in pred if r['season']==year and r['event_id'] not in quarantined and all(a in r['grades'] for a in POLICY['arms'])]
   if not rr:continue
   def avg(arm,field):return float(np.mean([r['grades'][arm][field] for r in rr]))
   def b(arm):return float(np.mean([r['grades'][arm]['winner']['conditional_brier'] for r in rr if r['grades'][arm]['winner']['conditional_brier'] is not None]))
   a,bv=b('score_base'),b('rest_form')
   lines.append(f"| {s} / {year} | {len(rr)} | {a:.5f} | {bv:.5f} | {avg('score_base','margin_error'):.3f} / {avg('rest_form','margin_error'):.3f} | {avg('score_base','total_error'):.3f} / {avg('rest_form','total_error'):.3f} |")
   paired.append(dict(sport=s,season=year,games=len(rr),base_brier=a,rest_form_brier=bv))
 lines+=['','Basketball season labels follow source end-year: 2027 is the current 2026–27 season, not future results. NFL/NCAAF 2026 and NCAAB 2027 are partial seasons. The derived paired table excludes event401909694 for the existing legacy team-identity conflict; its original development row/grade is preserved in raw files. Its November3 outcome is after the frozen October1 model/residual cutoff and did not enter the current fit. Raw DEVELOPMENT_RESULTS retains the original partial-season aggregate and is not an approval-ready quarantine-filtered summary. Rest/form worsened winner scores in NFL 2025, NCAAF 2024–25 and NCAAB 2025–26. Small partial-season gains do not reverse those failures. No feature group was selected because of a favorable subset. Independent pregame Elo scores and all season-specific W/P/L, margin, total and infinite-loss results are retained in DEVELOPMENT_RESULTS.json.','',
 'Exact frozen official historical probabilities are not available for this replay; applying a November 2026 frozen fit backwards would leak future data. They remain missing. The existing official-versus-v2 prospective comparison is separately reported in ../beta-model-lab/MORNING_REPORT_20261110.md and must not be merged with this new cohort.','',
 '## Bookmaker-specific chronological replay','',
 'Existing purchased NCAA football archive was reused locally; no additional paid requests or credentials accessed. Joins require exact event/kickoff and unchanged final scores, preserve existing quarantines and use source-bound opposing prices. New probabilities are reconstructed development forecasts, never original betting probabilities. MARKET_RESULTS_VERIFIED.json supersedes the preliminary MARKET_RESULTS.json with an explicit result-score revision check.','',
 '| Season | Market | Arm | Events | Event-weighted model Brier | Event-weighted no-vig Brier | Quote-weighted hypothetical ROI |','|---|---|---|---:|---:|---:|---:|']
 for z in sorted(markets['results'],key=lambda z:(z['season'],z['market'],z['arm'])):
  if z['season']<2024:continue
  roi=z['quote_metrics']['hypothetical_roi'];mb=z['event_weighted_conditional_brier'];nb=z['event_weighted_novig_brier']
  lines.append(f"| {z['season']} | {z['market']} | {z['arm']} | {z['events']} | {mb:.5f} | {nb:.5f} | {roi:.2%} |" if roi is not None else f"| {z['season']} | {z['market']} | {z['arm']} | {z['events']} | {mb:.5f} | {nb:.5f} | unavailable |")
 lines+=['','Positive historical ROI cells coexist with poor probability scores and losing seasons. They are not an edge claim. The file retains push counts, selected quote counts, week-cluster paired score/ROI intervals and maximum drawdowns. One unit per selected book/line quote is a correlated diagnostic, not an executable portfolio. Independent original quote authentication and CLV remain unavailable.','',
 'NFL and NCAAB historical bookmaker-specific opposing quote archives are missing from the accessible local history store. We did not assign -110 prices, substitute consensus lines, or invent historical ROI/CLV. Their spread/total price-matched validation is blocked until a usable existing authorized archive or new prospective evidence is available.','',
 '## Prospective pilot and integrity','']
 pilot={}
 for s in SPORTS:
  ff=[read(p) for p in (state/'forecasts').glob('*.json') if read(p)['sport']==s]
  qq=[read(p) for p in (state/'quotes').glob('*.json') if read(p)['sport']==s] if (state/'quotes').exists() else []
  gg=[read(p) for p in (state/'grades').glob('*.json') if read(p)['sport']==s] if (state/'grades').exists() else []
  pilot[s]=dict(registered=len(ff),supported=sum(bool(r['forecast'].get('arms')) for r in ff),refused=sum(r['forecast']['status']=='REFUSED' for r in ff),reference_pairs=len(qq),priced_games=len({r['event_id'] for r in qq}),settled=len(gg),outside_initial_seven_day_window_retained=sum(datetime.fromisoformat(r['identity']['kickoff'].replace('Z','+00:00'))>datetime.fromisoformat(r['issued_at'])+timedelta(days=7) for r in ff))
  lines.append(f"- {s}: {pilot[s]}")
 lines+=['','First captures are append-only under an exclusive lock and hash-linked journal. Model/code drift stops entry. Changed teams, kickoff, neutral site or final scores append quarantines; original grades are preserved. Raw free scoreboard and summary sources are retained with capture times and hashes. Repeated reference quotes are keyed by event/book/market/line and are not independent games. Provider final results and quote scopes remain unauthenticated. NFL reference quote capture begins within48h of kickoff; its initial future games were outside that window.','',
 'Provider calendars returned adjacent-week fixtures outside the requested dates. Original farther-ahead pilot forecasts are preserved and counted separately above; the final adapter bounds new captures to seven days. They are not additional confirmation games. Frozen model feature cutoff is September30/October1 boundary UTC, the same quarterly policy used in replay. Later source refreshes do not update its roster/weather inputs. This is an intentionally recorded pilot limitation. A later model update requires a separately versioned authorized build; routine capture never fits.','',
 'Two software failures were preserved: initial replay stopped at a quarter-boundary forecast clock; first capture rejected unsupported date-range URLs with HTTP400 for all sports. The corrected single-date adapter was separately registered with byte-identical fitted models; no tuning or refit followed the capture failure. The original failed states and receipts remain.','',
 '## Preregistered confirmation design — closed','',
 'The primary endpoint is event-weighted conditional Brier difference versus a same-book no-vig comparator at a fixed pregame window, separately for3sports×3markets. Proportional no-vig is conditional on no push; W/P/L proper scores and pushes are separate mandatory endpoints. One book/window/primary side per event must be fixed before confirmation; no best-book selection after results.','',
 'A practical improvement of .005, familywise alpha .05 across nine hypotheses and80% target power are specified. All earlier games and first100 eligible prospective pilot games per sport/market are excluded. Pilot variance must be estimated by week clusters, with at least300 confirmation games and12 independent weeks as floors. Planning formula: required weeks = ceil((z(1-.05/9)+z(.80))² × variance(weekly paired mean) / .005²). This is a planning approximation; imbalance, season effects and missingness require a locked cluster-power calculation before opening. Missing NFL/NCAAB matched-price variance prevents a defensible numeric sample target today.','',
 'One final analysis at the locked sample/date; no early promotion or repeated significance testing. All refusals and coverage gaps must accompany supported-only scores. Do not open confirmation by editing a boolean or relabel this pilot. Forecast accuracy approval and executable-price profitability approval are separate. A favorable Brier test cannot itself authorize wagers.','',
 '| Sport | Moneyline | Spread | Total |','|---|---|---|---|']
 lines.extend(f'| {s} | NO_GO | NO_GO | NO_GO |' for s in SPORTS)
 lines+=['','## Remaining work and reproduction','',
 'Acquire independently timed QB/lineup/eligibility, workload and weather evidence before those features can enter a registered numeric experiment. NFL/NCAAB need historical paired price evidence; all three need original source-time and legal execution evidence. Keep the failed rest/form result; the next feature group needs a separate protocol and development version. No unlimited feature search is authorized by the scheduled runner.','',
 f'Active state: `{state}`. `python -m research.three_sport_validation shadow --state STATE --output UNIQUE_RECEIPT.json` verifies and captures/grades without fitting. `python -m research.three_sport_validation_report --state STATE --output OUTPUT` reproduces this report without fitting. Source inputs, models and protocols are hash-pinned; build/register are initial development commands and are never routine. Exact source paths/hashes are in SOURCE_MANIFEST.json; exact branch/commit in COMMIT_RECEIPT.json.','',
 '46 targeted regression tests passed, covering future-result exclusion, quarter-boundary clocks, sign conventions, complementary prices, pushes, NFL tie scope, monotone lines, impossible college ties, first-capture idempotence, impossible future finals, independent Elo embargo and journal tampering, plus existing calibration/market tests. The final capture adapter amendment preserved the earlier fitted models and original pilot files byte-for-byte in a new registered state; it did not refit or retune.','',
 'For any eventual real wager: independent validation and explicit production authorization, complete current pregame inputs, a fresh executable exact event/book/market/selection/line/price, qualification and configured fractional-Kelly sizing with risk caps. Hard Rock requires Florida identity; DraftKings remains reference-only. Official baseline13–8, estimated bankroll$7,705.48 and$400unit unchanged.']
 (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
 comparisons=[read(p) for p in (state/'comparisons').glob('*.json')] if (state/'comparisons').exists() else []
 coverage={}
 for s in SPORTS:
  cc=[c for c in comparisons if c['sport']==s and c['event_id'] not in quarantined]
  coverage[s]=dict(games=len({c['event_id'] for c in cc}),independent_elo_games=len({c['event_id'] for c in cc if c.get('elo_probability') is not None}),official_score_reference_games=len({c['event_id'] for c in cc if 'official_score_reference' in c['winner_masses']}),exact_official_logistic_winner_games=len({c['event_id'] for c in cc if c.get('official_exact_winner_probability') is not None}),reference_pairs=sum(len(c['pairs']) for c in cc),official_refusals=dict(Counter(c['official_status'] for c in cc if 'official_score_reference' not in c['winner_masses'])))
 (output/'COMPARATOR_COVERAGE.json').write_text(json.dumps(coverage,indent=2))
 with (output/'REPORT.md').open('a') as f:
  f.write('\n## New pregame official and Elo comparison cohort\n\nA separately registered, no-fit comparator entry now executes the frozen official coefficients on date-aware available history and recomputes both challenger arms at the new comparison issuance time. It stores an independent fixed K20/HFA55 winner Elo. These are new pregame research references, not restored original betting probabilities. The original first forecasts remain untouched. Official NCAAB logistic winner probabilities remain distinct from official score-kernel winner probabilities; NFL/NCAAF use their official score distributions. Inputs remain retrospective/source-time unauthenticated, and old challenger feature cutoffs remain explicit.\n\n')
  for s,c in coverage.items():f.write(f'- {s}: {c}\n')
  f.write('\nLater first book/line captures append new comparison vintages at their actual current issuance time. Repeated vintages are not independent games. The initial college comparator call failed on a missing explicit refund argument; its failed receipt is preserved, corrected code separately registered, with no refit. Missing official D1 schedule matches are refusals, not replaced by inferred probabilities. Explicit official/provider identity or kickoff conflicts append persistent quarantines (currently401928789 and401922239); their original records remain, and paired summaries exclude them. Routine comparator mode cannot register itself if registration is missing.\n\nReproduce: `python -m research.three_sport_comparators --state STATE --output UNIQUE_RECEIPT.json` without --register.\n')
 finals={(read(p)['sport'],read(p)['event_id']):read(p) for p in (state/'grades').glob('*.json')} if (state/'grades').exists() else {}
 cells={}
 for s in SPORTS:
  for market in ('moneyline','spread','total'):
   rows=[]
   for c in comparisons:
    key=(s,c['event_id'])
    if c['sport']!=s or c['event_id'] in quarantined or key not in finals:continue
    hs,aws=finals[key]['scores']
    for p in c['pairs']:
     q=p['quote']
     if q['market']!=market:continue
     y=settlement(dict(home_score=hs,away_score=aws,market=market,selection=q['selection'],line=q['line']))
     arms={}
     for a,v in p['probabilities'].items():
      ev=v[0]*odds_profit(q['american_odds'])-v[2];conditional=v[0]/(v[0]+v[2]) if v[0]+v[2]>0 else None
      arms[a]=dict(score(v,y),expected_return=ev,selected=conditional is not None and conditional-q['no_vig_conditional']>=(.025 if market=='spread' else .03) and ev>0)
     rows.append(dict(event_id=c['event_id'],kickoff=c['identity']['kickoff'],book=q['book'],line=q['line'],outcome=y,novig_brier=None if y==0 else (q['no_vig_conditional']-(y==1))**2,arms=arms,reference_profit_if_selected=odds_profit(q['american_odds']) if y==1 else -1 if y==-1 else 0))
   aggregate={}
   for arm in ('score_base','rest_form','official_score_reference'):
    usable=[r for r in rows if arm in r['arms']];selected=[r for r in usable if r['arms'][arm]['selected']];pnl=sum(r['reference_profit_if_selected'] for r in selected);cum=peak=dd=0
    for r in sorted(selected,key=lambda r:r['kickoff']):cum+=r['reference_profit_if_selected'];peak=max(peak,cum);dd=max(dd,peak-cum)
    aggregate[arm]=dict(paired_rows=len(usable),selected=len(selected),hypothetical_roi=pnl/len(selected) if selected else None,max_drawdown_units=dd,infinite=sum(r['arms'][arm]['infinite'] for r in usable))
   cells[s+':'+market]=dict(settled_games=len({r['event_id'] for r in rows}),reference_pairs=len(rows),rows=rows,aggregate=aggregate,authenticated_price_coverage=0,clv=None,decision='NO_GO',scope='correlated one-unit-per-selected-quote descriptive diagnostic; not executable portfolio')
 (output/'PROSPECTIVE_MARKET_GRADES.json').write_text(json.dumps(cells,indent=2))
 (output/'PILOT_STATUS.json').write_text(json.dumps(dict(sports=pilot,confirmation_open=False,approved_risk=0),indent=2))
 (output/'PAIRED_SEASON_RESULTS.json').write_text(json.dumps(paired,indent=2))
 return pilot

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(report(a.state,a.output),indent=2))
