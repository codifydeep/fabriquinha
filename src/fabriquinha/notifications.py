"""Model-free event outbox. Delivery uncertainty never authorizes blind resend."""
import http.client
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from .artifacts import digest
from .effects import Journal, write_json

EVENTS=dict(created='Assignment registered',spawned='Activity started',worker_registered='Activity started',
    scheduled='Waiting for an external effect; worker released',
    reclaimed='Worker claim released; delivery not approved',
    review_requested='Submitted for independent review',changes_requested='Review finished: changes requested',
    review_reopened='Response received; original author resumes',
    completed='Activity completed (not release homologation)',blocked='Activity blocked; technical diagnosis required',
    crashed='Worker crashed; recovery pending',timed_out='Worker timed out; recovery pending',
    gave_up='Automatic attempts exhausted; technical diagnosis required',
    block_loop_detected='Repeated impediment; technical intervention required',unblocked='Activity resumed; gates still required')


class RetryLater(Exception):
    def __init__(self,seconds=5):self.seconds=seconds


class Rejected(Exception):pass


class Transport:
    """Fixed Telegram sendMessage or a loopback qualification sink; no redirects."""
    def __init__(self,project,path):
        path=Path(path)
        if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('private notification route required')
        value=json.loads(path.read_bytes());self.version=digest(value)
        self.local=value.get('transport')=='local'
        if self.local:
            if not project.qualification or set(value)!={'transport','endpoint'}:raise ValueError('local qualification route required')
            url=urlsplit(value['endpoint'])
            if (url.scheme!='http' or url.hostname!='127.0.0.1' or not url.port or url.path not in ('','/')
                    or url.query or url.fragment or url.username or url.password):raise ValueError('loopback sink required')
            self.host,self.port=url.hostname,url.port;self.destination=digest(value)
        else:
            if (project.qualification or set(value)-{'transport','bot_token','chat_id','thread_id'}
                    or value.get('transport')!='telegram' or not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',value.get('bot_token',''))
                    or not re.fullmatch(r'-?[0-9]{1,22}',str(value.get('chat_id','')))
                    or value.get('thread_id') is not None and (type(value['thread_id']) is not int or value['thread_id']<1)):
                raise ValueError('explicit Telegram bot/chat/thread required outside qualification')
            self.token,self.chat,self.thread=value['bot_token'],str(value['chat_id']),value.get('thread_id')
            self.destination=digest(dict(bot=self.token.split(':')[0],chat=self.chat,thread=self.thread))

    def request(self,method,path,body=None):
        connection=(http.client.HTTPConnection(self.host,self.port,timeout=3) if self.local
                    else http.client.HTTPSConnection('api.telegram.org',timeout=3))
        try:
            try:connection.connect()
            except OSError:raise RetryLater(5) from None  # No HTTP bytes sent.
            connection.request(method,path,json.dumps(body) if body is not None else None,
                {'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise ValueError('notification response exceeded bound')
            data=json.loads(raw)
            if response.status==429 and data.get('ok') is False:
                delay=(data.get('parameters') or {}).get('retry_after',30)
                raise RetryLater(delay if type(delay) is int and delay>0 else 30)
            if 400<=response.status<500 and data.get('ok') is False:raise Rejected()
            if response.status!=200 or data.get('ok') is not True:raise ValueError('uncertain notification response')
            result=data.get('result')
            if not isinstance(result,dict) or type(result.get('message_id')) is not int:
                raise ValueError('notification acknowledgement missing')
            return {'message_id':result['message_id']}
        finally:connection.close()

    def send(self,message,key):
        if self.local:return self.request('POST','/notifications',dict(key=key,message=message))
        body=dict(chat_id=self.chat,text=message['text'],allow_paid_broadcast=False)
        if self.thread is not None:body['message_thread_id']=self.thread
        return self.request('POST','/bot'+self.token+'/sendMessage',body)

    def observe(self,key):
        if not self.local:return None  # sendMessage has no client idempotency lookup.
        try:return self.request('GET','/notifications/'+key)
        except (Rejected,RetryLater):return None


class Outbox:
    def __init__(self,project,store,*,clock=time.time):
        self.project,self.store,self.clock=project,store,clock
        self.journal=Journal(store.root/'effects/notifications');self.root=self.journal.root

    def save(self,path,value):
        write_json(path,value)
        fd=os.open(self.root,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def enqueue(self,key,message):
        identity=dict(project=self.project.fingerprint(),key=key)
        key=digest(identity);path=self.root/(key+'.json')
        if path.exists():return key  # Immutable message; never wait on a slow sender.
        with self.journal.lock(key):
            if not path.exists():self.save(path,dict(identity=identity,key=key,message=message,state='queued',
                created=self.clock(),attempts=0,next_at=0,destination=None))
        return key

    def records(self):
        records=[]
        for path in self.root.glob('*.json'):
            if not re.fullmatch('[a-f0-9]{64}',path.stem):continue
            try:
                record=json.loads(path.read_bytes())
                required={'identity','key','message','state','created','attempts','next_at','destination'}
                if (not isinstance(record,dict) or not required<=set(record) or record['key']!=path.stem
                        or not isinstance(record['identity'],dict) or not isinstance(record['message'],dict)
                        or not isinstance(record['message'].get('text'),str) or not 1<=len(record['message']['text'])<=4096
                        or type(record['attempts']) is not int or record['attempts']<0
                        or type(record['created']) not in (int,float) or type(record['next_at']) not in (int,float)
                        or digest(record['identity'])!=path.stem or record['identity'].get('project')!=self.project.fingerprint()
                        or record['state'] not in ('queued','sending','uncertain','rejected','delivered','archived')):
                    raise ValueError('invalid notification record')
            except (ValueError,OSError):record=dict(key=path.stem,state='corrupt',created=0)
            records.append(record)
        return sorted(records,key=lambda record:(record['created'],record['key']))

    def archive_unsent(self,keys,*,reason):
        """Explicit activation cut; caller must keep the sender stopped/paused.

        Preserve messages in place, never call them delivered and never retire
        an attempted/uncertain send. Exact keys make interrupted cuts resumable.
        """
        if (not isinstance(keys,list) or len(set(keys))!=len(keys)
                or any(not isinstance(k,str) or not re.fullmatch('[a-f0-9]{64}',k) for k in keys)
                or not isinstance(reason,str) or not 1<=len(reason)<=500):
            raise ValueError('exact notification keys and bounded archival reason required')
        def eligible(record):
            if (record.get('state') not in ('queued','archived') or record.get('attempts')!=0
                    or record.get('destination') is not None
                    or record.get('state')=='archived' and record.get('archive_reason')!=reason):
                raise ValueError('only never-attempted notifications may be archived')
        records={r['key']:r for r in self.records()}
        for key in keys:
            if key not in records:raise ValueError('unknown notification key')
            eligible(records[key])
        for key in keys:
            with self.journal.lock(key):
                path=self.root/(key+'.json');record=json.loads(path.read_bytes());eligible(record)
                if record['state']=='archived':continue
                record.update(state='archived',archive_reason=reason,archived_at=self.clock())
                self.save(path,record)
        return dict(archived=len(keys),keys_digest=digest(sorted(keys)),delivered=0)

    def capture(self,conn):
        with self.journal.lock('cursor'):
            path=self.root/'cursor.json'
            if not path.exists():
                last=conn.execute('SELECT * FROM task_events ORDER BY id DESC LIMIT 1').fetchone()
                self.save(path,dict(project=self.project.fingerprint(),cursor=last['id'] if last else 0,
                    anchor=self.anchor(last) if last else None))
                return  # Do not replay an existing board's history on activation.
            cursor=json.loads(path.read_bytes())
            if cursor['project']!=self.project.fingerprint():raise ValueError('outbox belongs to another project')
            if cursor['cursor']:
                row=conn.execute('SELECT * FROM task_events WHERE id=?',(cursor['cursor'],)).fetchone()
                if not row or self.anchor(row)!=cursor['anchor']:raise ValueError('board history changed; explicit outbox rebind required')
            rows=conn.execute('SELECT e.*,COALESCE(r.profile,t.assignee) AS actor,t.body FROM task_events e '
                'JOIN tasks t ON t.id=e.task_id LEFT JOIN task_runs r ON r.id=e.run_id WHERE e.id>? ORDER BY e.id LIMIT 200',
                (cursor['cursor'],)).fetchall()
            for row in rows:
                if row['kind'] in EVENTS:
                    phase=conn.execute("SELECT payload FROM task_events WHERE run_id=? AND kind='claimed' ORDER BY id LIMIT 1",(row['run_id'],)).fetchone()
                    try:body=json.loads(row['body'] or '{}')
                    except ValueError:body={}
                    mode='review' if phase and json.loads(phase[0] or '{}').get('source_status')=='review' else (body.get('kind','activity') if isinstance(body,dict) else 'activity')
                    mode=mode if mode in ('review','tests','implementation','diagnostic','integration','brief','plan','release') else 'activity'
                    actor=row['actor'] if re.fullmatch('[a-z][a-z0-9_-]{0,63}',row['actor'] or '') else 'controller'
                    task=row['task_id'] if re.fullmatch('t_[a-f0-9]{8,64}',row['task_id']) else 'unidentified-card'
                    event='started' if row['kind'] in ('spawned','worker_registered') else row['kind']
                    key='run:'+str(row['run_id'])+':started' if event=='started' else 'event:'+str(row['id'])
                    description=EVENTS[row['kind']]
                    if row['kind']=='review_requested' and isinstance(body,dict) and body.get('kind')=='brief':
                        description='Awaiting scoped CEO business input; not technical, budget or delivery approval'
                    if row['kind']=='completed' and isinstance(body,dict) and body.get('kind')=='release':
                        description='Release closed without qualified acceptance; technical diagnosis required'
                        proof=conn.execute('SELECT metadata FROM task_runs WHERE id=?',(row['run_id'],)).fetchone()
                        try:
                            metadata=json.loads(proof[0] or '{}') if proof else {}
                            record=self.store.receipt(metadata['release_acceptance'],kind='release_acceptance');data=record['payload']
                            if (record['binding']!=dict(actor='controller',task=task,release=body['release'],contract=digest(body))
                                    or data['project']!=self.project.fingerprint() or data['state']!='HOMOLOGADA'
                                    or data['qualification'] is not self.project.qualification):raise ValueError('foreign release evidence')
                            description=('Deterministic release qualification completed; not autonomous product delivery' if self.project.qualification
                                else 'Release HOMOLOGADA')+'\nCommit: '+data['commit']+'\nURL: '+data['url']
                        except (ValueError,KeyError,TypeError,OSError):pass
                    text=f'[{self.project.namespace}] {actor} | {task} | run {row["run_id"] or "-"} | {mode}\n{description}'
                    self.enqueue(key,dict(task=task,run=row['run_id'],actor=actor,mode=mode,event=event,text=text))
                cursor['cursor']=row['id']
                cursor['anchor']=self.anchor(row)
            self.save(path,cursor)  # Only after every preceding message is durable.

    @staticmethod
    def anchor(row):return digest({key:row[key] for key in ('id','task_id','run_id','kind','payload','created_at')})

    def flush(self,transport,*,limit=8):
        throttle=self.root/'throttle.json'
        if throttle.exists():
            value=json.loads(throttle.read_bytes())
            if value['destination']==transport.destination and self.clock()<value['until']:return
        for record in self.records():
            if limit<=0:break
            key=record['key'];path=self.root/(key+'.json')
            if record['state'] in ('delivered','archived','corrupt'):continue
            with self.journal.lock(key):
                record=json.loads(path.read_bytes())
                version=getattr(transport,'version',transport.destination)
                if record['state']=='rejected' and record.get('version')!=version and record.get('destination')==transport.destination:
                    record.update(state='queued',next_at=0)
                if record['state']=='rejected' or self.clock()<record['next_at']:continue
                if record['destination'] not in (None,transport.destination):
                    record.update(state='rejected',last_error='DestinationChanged');self.save(path,record);continue
                record.update(destination=transport.destination,version=version)
                observe=record['state'] in ('sending','uncertain')
                if not observe:
                    record.update(state='sending',attempts=record['attempts']+1);self.save(path,record)
                limit-=1
                try:
                    result=transport.observe(key) if observe else transport.send(record['message'],key)
                    if result is None:record.update(state='uncertain',next_at=self.clock()+30)
                    else:record.update(state='delivered',receipt=result,delivered_at=self.clock())
                except RetryLater as error:
                    until=self.clock()+max(1,error.seconds)
                    record.update(state='uncertain' if observe else 'queued',
                        next_at=until,last_error='NotAccepted')
                    self.save(throttle,dict(destination=transport.destination,until=until))
                except Rejected:
                    record.update(state='uncertain' if observe else 'rejected',last_error='Rejected')
                except Exception as error:
                    record.update(state='uncertain',next_at=self.clock()+30,last_error=type(error).__name__)
                self.save(path,record)
                if throttle.exists() and self.clock()<json.loads(throttle.read_bytes())['until']:break

    def summary(self):
        result={state:0 for state in ('queued','sending','uncertain','rejected','delivered','archived','corrupt')}
        for record in self.records():result[record['state']]+=1
        path=self.root/'error.json'
        result['last_error']=json.loads(path.read_bytes()) if path.exists() else None
        return result

    def loop(self,stop,path,enabled=None):
        while not stop.is_set():
            try:
                if (enabled is None or enabled.is_set()) and Path(path).exists():self.flush(Transport(self.project,path),limit=1)
            except Exception as error:
                self.save(self.root/'error.json',dict(category=type(error).__name__,at=self.clock()))
            stop.wait(1)


def validation_progress(card,store,project):
    if card['current_run_id'] is None:return None
    path=store.root/'progress'/(card['id']+'-'+str(card['current_run_id'])+'.json')
    if not path.exists():return None
    progress=json.loads(path.read_bytes());receipt=store.receipt(progress['receipt'])
    if (receipt['binding']==progress['binding'] and receipt['binding']['task']==card['id']
            and receipt['binding']['number']==card['current_run_id']
            and receipt['binding']['contract']==card.get('contract',receipt['binding']['contract'])
            and receipt['payload']['project']==project.fingerprint()):
        return dict(at=progress['at'],receipt=progress['receipt'],kind=receipt['kind'])
    return None


def alerts(outbox,cards,store,*,now,alert_after=600,escalate_after=1800):
    for card in cards:
        if card.get('corrective_task'):continue  # Its explicit corrective card owns current alerts; old failure stays visible.
        if card['status'] not in ('ready','review','running','blocked','triage'):continue
        if card['status'] in ('blocked','triage') and card.get('kind') not in ('brief','plan','tests','implementation','integration','diagnostic'):continue
        marker=card.get('run_started_at') if card['status']=='running' else card.get('last_event_at')
        marker=card.get('created_at',now) if marker is None else marker
        evidence=None
        progress=validation_progress(card,store,outbox.project) if card['status']=='running' else None
        if progress:marker=max(marker,progress['at']);evidence=progress['receipt']
        age=max(0,now-marker)
        for threshold,event in ((alert_after,'unattended'),(escalate_after,'stalled')):
            if age<threshold:continue
            key=digest([card['id'],card['current_run_id'],marker,evidence,event])
            actor=card['assignee'] if re.fullmatch('[a-z][a-z0-9_-]{0,63}',card['assignee'] or '') else 'controller'
            owner=card.get('technical_owner') or (outbox.project.technical_roles or {}).get('cto' if event=='stalled' else 'lead','techlead')
            if card.get('business_input') and 'error' not in card['business_input']:
                if event=='stalled':continue  # Business waits do not escalate to the CTO as technical stalls.
                request=card['business_input']['request']
                outbox.enqueue(key,dict(task=card['id'],run=None,actor='ceo',mode='brief',event='business_input_pending',
                    text=f'[{outbox.project.namespace}] {card["id"]} | CEO business response pending: {request}. Not technical or budget approval.'))
                continue
            text=f'[{outbox.project.namespace}] {card["id"]} | {actor} | {event}\nNo new controller-validated evidence for {int(age)}s. Technical owner: {owner}. Not a delivery result.'
            outbox.enqueue(key,dict(task=card['id'],run=card['current_run_id'],actor=actor,mode='monitor',event=event,text=text))
