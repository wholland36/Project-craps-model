import json,hashlib
from research.beta_v2.markets import pair_quotes,match_quotes,choose_ticket,settle,price_changes,summarize_returns
T='2026-11-05T16:00:00+00:00'
E={'event_id':'1','kickoff':'2026-11-05T23:00:00+00:00'}
def quotes():return [{'sport':'NFL','event_id':'1','book':'b','quote_id':s,'snapshot_id':'snap','market':'spread','period':'full_game','scope':'including_overtime','side':s,'line':l,'decimal_price':1.91,'executable':True,'published_at':'2026-11-05T15:59:00+00:00','observed_at':T} for s,l in [('home',-3),('away',3)]]
def test_pair_vig_and_failures():
 r=pair_quotes('NFL',E,T,quotes());assert len(r['pairedrows'])==1 and r['pairedrows'][0]['rows'][0]['no_vig_probability']==.5
 for field,value in [('book','other'),('line',4),('period','first_half'),('observed_at','2026-11-05T16:01:00+00:00'),('published_at','2026-11-05T14:00:00+00:00')]:
  q=quotes();q[1][field]=value;assert not pair_quotes('NFL',E,T,q)['pairedrows']
 assert not pair_quotes('NFL',E,T,quotes()+quotes())['pairedrows']

def test_private_hash_body_bound_no_network(tmp_path):
 d=tmp_path/'markets'/'inbox'/'NFL';d.mkdir(parents=True)
 raw=tmp_path/'raw.json';rows=quotes();body=json.dumps({'quotes':rows}).encode();raw.write_bytes(body);h=hashlib.sha256(body).hexdigest()
 inbox={'quotes':[dict(r,source_sha256=h) for r in rows],'sources':[{'body_path':str(raw),'sha256':h,'independently_authenticated':True,'authentication_evidence':'manual receipt','published_at':'2026-11-05T15:59:00+00:00','observed_at':T}]}
 path=d/'1_final.json';path.write_text(json.dumps(inbox));assert len(match_quotes('NFL',E,T,tmp_path,'final')['pairedrows'])==1
 inbox['quotes'][0]['decimal_price']=4;path.write_text(json.dumps(inbox));assert not match_quotes('NFL',E,T,tmp_path,'final')['pairedrows']
 assert match_quotes('NFL',E,T,tmp_path,'other')['paid_calls']==0

def test_ticket_push_void_exposure_and_zero_support():
 pairs=pair_quotes('NFL',E,T,quotes())['pairedrows'];f={'home':{'win':.6,'push':.1,'loss':.3},'away':{'win':.3,'push':.1,'loss':.6}}
 r=choose_ticket('1',pairs,f);assert r['ticket']['side']=='home' and r['ticket']['stake']==1
 assert choose_ticket('1',pairs,f,already_selected=['1'])['ticket'] is None
 assert choose_ticket('1',pairs,{'home':{'win':.6,'loss':.4}})['ticket'] is None
 ticket=dict(r['ticket'],week='2026-W45')
 assert settle(ticket,'push')['profit']==0 and settle(ticket,'push')['turnover']==1
 assert settle(ticket,'void')['turnover']==0
 r=summarize_returns([settle(ticket,'win'),settle(ticket,'loss')],['2026-W45','2026-W46'])
 assert r['zero_support_weeks']==1 and r['supported_weeks']==1 and r['confidence_interval'] is None

def test_clv_same_line_book_pregame():
 a=quotes()[0];b=dict(a,decimal_price=1.8,observed_at='2026-11-05T22:00:00+00:00')
 assert price_changes(a,b,E['kickoff'])['same_line_price_clv']>0
 assert price_changes(a,dict(b,line=-4),E['kickoff'])['same_line_price_clv'] is None
 assert price_changes(a,dict(b,book='other'),E['kickoff'])['status']=='MISSING'
 assert price_changes(a,dict(b,observed_at=E['kickoff']),E['kickoff'])['status']=='MISSING'

def test_unsupported_quarter_lines_moneyline_line_total_and_tie_policy():
 q=quotes();q[0]['line']=-3.25;q[1]['line']=3.25
 assert not pair_quotes('NFL',E,T,q)['pairedrows']
 q=quotes()
 for r in q:r.update(market='moneyline',tie_settlement='push_on_tie')
 assert not pair_quotes('NFL',E,T,q)['pairedrows']
 for r in q:r['line']=None
 assert len(pair_quotes('NFL',E,T,q)['pairedrows'])==1
 for r in q:r.pop('tie_settlement')
 assert not pair_quotes('NFL',E,T,q)['pairedrows']
 q=quotes()
 for r in q:r.update(market='total',line=0,side='over' if r['side']=='home' else 'under')
 assert not pair_quotes('NFL',E,T,q)['pairedrows']
