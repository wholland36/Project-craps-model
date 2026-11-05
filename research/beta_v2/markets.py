"""Exact-book pregame comparison using private authorized quotes; no network calls.

Expected inbox: markets/inbox/SPORT/EVENT_HORIZON.json with `quotes` and source
receipts. Each receipt binds a private body file containing a `quotes` list. The
inbox never authenticates a source merely by declaring a boolean.
"""
from pathlib import Path
import json
import hashlib
from collections import defaultdict
from .context import instant,finite,safe

MAX_AGE_SECONDS=900

def _authenticated_quotes(state,inbox,asof):
 sources={};missing=[];root=Path(state).resolve()
 for s in inbox.get('sources',[]):
  try:
   p=Path(s['body_path']).resolve()
   if root not in p.parents:raise ValueError('outside private state')
   body=p.read_bytes()
   if hashlib.sha256(body).hexdigest()!=s['sha256']:raise ValueError('hash mismatch')
   if s.get('independently_authenticated') is not True or not s.get('authentication_evidence'):raise ValueError('authentication missing')
   if not instant(s['published_at'])<=instant(s['observed_at'])<=instant(asof):raise ValueError('clock unverified')
   rows=json.loads(body).get('quotes',[])
   sources[s['sha256']]={json.dumps(r,sort_keys=True,separators=(',',':')) for r in rows}
  except (KeyError,ValueError,OSError,TypeError):missing.append('source_unauthenticated_or_invalid')
 valid=[]
 for row in inbox.get('quotes',[]):
  bound={k:v for k,v in row.items() if k!='source_sha256'}
  if json.dumps(bound,sort_keys=True,separators=(',',':')) not in sources.get(row.get('source_sha256'),set()):missing.append('quote_not_source_bound');continue
  valid.append(row)
 return valid,missing

def pair_quotes(sport,event,asof,quotes,max_age=MAX_AGE_SECONDS):
 groups=defaultdict(list);missing=[];accepted=[]
 for r in quotes:
  flags=[]
  if r.get('sport')!=sport or str(r.get('event_id'))!=str(event['event_id']):flags.append('event_sport_mismatch')
  if not r.get('book') or not r.get('quote_id') or not r.get('snapshot_id'):flags.append('book_or_quote_identity_missing')
  if r.get('market') not in ('moneyline','spread','total'):flags.append('market_unsupported')
  if r.get('period')!='full_game' or r.get('scope') not in ('including_overtime','regulation'):flags.append('period_scope_missing')
  if r.get('scope')!=event.get('market_scope','including_overtime'):flags.append('settlement_scope_mismatch')
  if not finite(r.get('decimal_price')) or r['decimal_price']<=1:flags.append('price_invalid')
  if r.get('executable') is not True:flags.append('offer_not_executable')
  if r.get('market') in ('spread','total') and not finite(r.get('line')):flags.append('line_missing')
  if r.get('market')=='moneyline' and r.get('line') is not None:flags.append('moneyline_line_must_be_null')
  if r.get('market') in ('spread','total') and finite(r.get('line')) and abs(r['line']*2-round(r['line']*2))>1e-9:flags.append('quarter_or_nonstandard_line_unsupported')
  if r.get('market')=='total' and finite(r.get('line')) and r['line']<=0:flags.append('total_must_be_positive')
  if r.get('market')=='moneyline' and r.get('tie_settlement') not in ('push_on_tie','tie_impossible'):flags.append('moneyline_tie_settlement_unverified')
  try:
   pub=instant(r['published_at']);obs=instant(r['observed_at']);cut=instant(asof)
   if not pub<=obs<=cut<instant(event['kickoff']):flags.append('not_exact_pregame_clock')
   if (cut-pub).total_seconds()>max_age:flags.append('quote_stale')
  except (KeyError,ValueError):flags.append('quote_clock_missing')
  if flags:missing.extend(flags);continue
  line=abs(r['line']) if r['market']=='spread' else r.get('line')
  key=(r['book'],r['market'],r['period'],r['scope'],line,r['snapshot_id'],r['published_at'],r['observed_at'])
  groups[key].append(r)
 for key,rows in groups.items():
  market=key[1];sides={'over','under'} if market=='total' else {'home','away'}
  if len(rows)!=2 or {r.get('side') for r in rows}!=sides:missing.append('opposing_pair_missing_or_ambiguous');continue
  if market=='spread' and abs(sum(r['line'] for r in rows))>1e-9:missing.append('spread_lines_not_opposites');continue
  den=sum(1/r['decimal_price'] for r in rows)
  if den<=0:missing.append('invalid_overround');continue
  accepted.append({'book':key[0],'market':market,'period':key[2],'scope':key[3],'line':key[4],'snapshot_id':key[5],'published_at':key[6],'observed_at':key[7],'overround':den-1,'rows':[dict(r,no_vig_probability=(1/r['decimal_price'])/den) for r in rows],'probability_basis':'conditional_on_no_push' if market!='moneyline' else 'two_way_market_requires_explicit_tie_scope','research_only':True})
 return {'pairedrows':accepted,'missing':sorted(set(missing))}

def match_quotes(sport,event,asof,state,horizon):
 """Only the typed authenticated private inbox; no paid API or raw export."""
 p=Path(state)/'markets'/'inbox'/safe(sport)/(safe(event['event_id'])+'_'+safe(horizon)+'.json')
 if not p.exists():return {'pairedrows':[],'missing':['authenticated_exact_cutoff_quotes_missing'],'paid_calls':0}
 inbox=json.loads(p.read_text());rows,missing=_authenticated_quotes(state,inbox,asof)
 result=pair_quotes(sport,event,asof,rows);result['missing']=sorted(set(result['missing']+missing));result['paid_calls']=0
 return result

def choose_ticket(event_id,pairs,forecasts,bankroll=100.,unit_fraction=.01,exposure_fraction=.01,minimum_ev=.03,already_selected=()):
 """Fixed highest-EV one-ticket rule; only preregistered W/P/L model forecasts.

 `forecasts[quote_id]`: win,push,loss. No-vig conditional probabilities must not
 be substituted for unconditional probabilities in expected return calculations.
 """
 if str(event_id) in {str(x) for x in already_selected}:return {'ticket':None,'reason':'event_exposure_already_used'}
 if not all(finite(x) for x in (bankroll,unit_fraction,exposure_fraction,minimum_ev)) or bankroll<=0 or not 0<unit_fraction<=exposure_fraction<=1:raise ValueError('invalid exposure policy')
 candidates=[]
 for pair in pairs:
  for q in pair['rows']:
   f=forecasts.get(q['quote_id'],{});probs=[f.get(k) for k in ('win','push','loss')]
   if any(not finite(x) or x<0 or x>1 for x in probs) or abs(sum(probs)-1)>1e-8:continue
   ev=probs[0]*(q['decimal_price']-1)-probs[2]
   if ev>=minimum_ev:candidates.append(dict(q,forecast=dict(f),expected_return=ev))
 if not candidates:return {'ticket':None,'reason':'no_supported_positive_ev_candidate'}
 winner=sorted(candidates,key=lambda q:(-q['expected_return'],q['book'],q['quote_id']))[0]
 winner.update(stake=bankroll*min(unit_fraction,exposure_fraction),event_id=str(event_id),policy='fixed-one-ticket-per-event-v1')
 return {'ticket':winner,'reason':'research_hypothetical_only'}

def settle(ticket,result):
 if result not in ('win','push','loss','void'):raise ValueError('unsupported settlement')
 stake=ticket['stake'];ret=stake*(ticket['decimal_price']-1) if result=='win' else -stake if result=='loss' else 0.
 return {'profit':ret,'turnover':0. if result=='void' else stake,'result':result,'event_id':ticket['event_id'],'week':ticket.get('week'),'hypothetical':True}

def price_changes(open_quote,close_quote,kickoff):
 keys=('sport','event_id','book','market','period','scope','side')
 if any(open_quote.get(k)!=close_quote.get(k) for k in keys):return {'status':'MISSING','reason':'exact_book_event_market_side_mismatch'}
 try:
  if not instant(open_quote['published_at'])<=instant(open_quote['observed_at'])<=instant(close_quote['observed_at'])<instant(kickoff) or not instant(close_quote['published_at'])<=instant(close_quote['observed_at']):raise ValueError('not pregame')
 except (KeyError,ValueError):return {'status':'MISSING','reason':'pregame_clocks_missing'}
 if any(not finite(q.get('decimal_price')) or q['decimal_price']<=1 for q in (open_quote,close_quote)):return {'status':'MISSING','reason':'price_invalid'}
 same_line=open_quote.get('line')==close_quote.get('line')
 return {'status':'COMPUTED','line_change':close_quote['line']-open_quote['line'] if finite(open_quote.get('line')) and finite(close_quote.get('line')) else None,'decimal_price_change':close_quote['decimal_price']-open_quote['decimal_price'],'same_line_price_clv':open_quote['decimal_price']/close_quote['decimal_price']-1 if same_line else None,'missing':[] if same_line else ['price_clv_requires_same_line'],'interpretation':'same-book price/line movement; not an edge proof'}

def summarize_returns(rows,expected_weeks=()):
 blocks=defaultdict(lambda:{'profit':0.,'turnover':0.,'tickets':0})
 for w in expected_weeks:blocks[str(w)]
 for r in rows:
  if r.get('week') is None:raise ValueError('week required for block summary')
  b=blocks[str(r['week'])];b['profit']+=r['profit'];b['turnover']+=r['turnover'];b['tickets']+=int(r['result']!='void')
 profit=sum(b['profit'] for b in blocks.values());turnover=sum(b['turnover'] for b in blocks.values())
 return {'profit':profit,'turnover':turnover,'roi':profit/turnover if turnover else None,'week_blocks':dict(sorted(blocks.items())),'supported_weeks':sum(b['turnover']>0 for b in blocks.values()),'zero_support_weeks':sum(b['turnover']==0 for b in blocks.values()),'confidence_interval':None,'ci_status':'NOT_COMPUTED_REQUIRES_PREREGISTERED_INDEPENDENT_BLOCK_SUPPORT'}
