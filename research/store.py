"""Private zero-risk shadow cohorts. These are not canonical approved forecasts."""
import json
import math
import fcntl
from functools import wraps
import sqlite3
from pathlib import Path
from project_craps.common import canonical,digest,instant,now,stamp


def serialized(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        if self._lock_depth:
            return method(self,*args,**kwargs)
        with self._lock_path.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            self._lock_depth=1
            try:return method(self,*args,**kwargs)
            finally:
                self._lock_depth=0
                fcntl.flock(lock,fcntl.LOCK_UN)
    return call


class ShadowStore:
    def __init__(self,path,clock=now):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self._lock_path=Path(str(path)+'.writer.lock');self._lock_depth=0
        self.db=sqlite3.connect(path,timeout=30,isolation_level=None);self.clock=clock
        self.initialize()

    @serialized
    def initialize(self):
        self.db.executescript('''
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS records (seq INTEGER PRIMARY KEY, key TEXT UNIQUE, payload TEXT, prev TEXT, sha TEXT);
        CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY REFERENCES records(key), payload TEXT, sha TEXT);
        CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'append only');END;
        CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'append only');END;
        CREATE TRIGGER IF NOT EXISTS results_no_update BEFORE UPDATE ON results BEGIN SELECT RAISE(ABORT,'append only');END;
        CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON results BEGIN SELECT RAISE(ABORT,'append only');END;
        ''');self.db.execute('PRAGMA foreign_keys=ON');self.verify()

    @serialized
    def verify(self):
        previous='GENESIS';count=0
        for seq,key,payload,prev,sha in self.db.execute('SELECT * FROM records ORDER BY seq'):
            count+=1;value=json.loads(payload)
            if seq!=count or prev!=previous or value['key']!=key or digest({'prev':prev,'payload':value})!=sha:
                raise ValueError('shadow registry corrupted')
            previous=sha
        results=[]
        for key,payload,sha in self.db.execute('SELECT * FROM results ORDER BY key'):
            if digest(json.loads(payload))!=sha or json.loads(payload)['key']!=key:raise ValueError('shadow result corrupted')
            results.append(sha)
        return {'count':count,'head_sha256':previous,'results_count':len(results),'results_sha256':digest(results)}

    @serialized
    def append(self,payload):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            anchor=self.verify()
            old=self.db.execute('SELECT payload FROM records WHERE key=?',(payload['key'],)).fetchone()
            if old:
                self.db.execute('COMMIT');return json.loads(old[0])
            actual=self.clock()
            if payload['approved_risk']!=0 or payload['model_approved'] is not False:raise ValueError('shadow cannot approve risk')
            if instant(payload['kickoff'])<=actual or instant(payload['issued_at'])>actual or (actual-instant(payload['issued_at'])).total_seconds()>300:
                raise ValueError('not a current pregame issuance')
            if not payload.get('predictions'):raise ValueError('shadow predictions required')
            for prediction in payload['predictions'].values():
                for field in ('home_win','home_tie'):
                    value=prediction[field]
                    if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('invalid shadow probability')
            first=None
            # Same event/provider ID can never silently switch teams or kickoff.
            for row in self.db.execute('SELECT payload FROM records'):
                prior=json.loads(row[0])
                if prior['sport']==payload['sport'] and prior['event_id']==payload['event_id'] and prior['identity']!=payload['identity']:
                    raise ValueError('event identity revision requires quarantine')
                if prior['sport']==payload['sport'] and prior['event_id']==payload['event_id'] and prior['protocol_sha256']==payload['protocol_sha256'] and first is None:first=prior['key']
            payload=dict(payload,first_shadow_key=first or payload['key'])
            payload=json.loads(canonical(payload));sha=digest({'prev':anchor['head_sha256'],'payload':payload})
            self.db.execute('INSERT INTO records VALUES (?,?,?,?,?)',(anchor['count']+1,payload['key'],canonical(payload),anchor['head_sha256'],sha))
            self.db.execute('COMMIT');return payload
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise

    @serialized
    def records(self):
        self.verify();return [json.loads(x[0]) for x in self.db.execute('SELECT payload FROM records ORDER BY seq')]

    @serialized
    def settle(self,games,observed_at):
        from math import log
        by_id={g['event_id']:g for g in games};count=0
        for record in self.records():
            event=by_id.get(record['event_id'])
            if not event or event['status']!='FINAL':continue
            identity={k:event[k] for k in record['identity']}
            if identity!=record['identity']:raise ValueError('shadow settlement identity revision')
            result_observed=event['observed_at']
            if not (instant(record['issued_at'])<instant(event['kickoff'])<instant(result_observed)<=instant(observed_at)<=self.clock()):
                raise ValueError('invalid outcome observation time')
            result={'key':record['key'],'identity':identity,'home_score':event['home_score'],'away_score':event['away_score'],
                    'observed_at':result_observed,'source_sha256':event.get('source_sha256'),'scores':{},'first_event_prediction':record['first_shadow_key']==record['key'],'official_pnl':0,'approved_risk':0}
            for variant,p in record['predictions'].items():
                y=int(event['home_score']>event['away_score']);prob=p['home_win']
                result['scores'][variant]={'home_win_brier':(prob-y)**2,'home_win_logloss':-log(max(1e-9,prob if y else 1-prob))}
            old=self.db.execute('SELECT payload FROM results WHERE key=?',(record['key'],)).fetchone()
            if old:
                prior=json.loads(old[0])
                if (prior['home_score'],prior['away_score'])!=(event['home_score'],event['away_score']):raise ValueError('changed shadow result requires quarantine')
                continue
            self.db.execute('INSERT INTO results VALUES (?,?,?)',(record['key'],canonical(result),digest(result)));count+=1
        return {'new_results':count,'anchor':self.verify()}

    def close(self):self.db.close()
