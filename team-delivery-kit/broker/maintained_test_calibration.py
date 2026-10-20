"""Durable approved snapshot -> ordinary calibration -> measured functional Red.

No author task is created and no product route is enabled. The old maintenance
state and all rejected source attempts remain immutable. Calibration still uses
the existing native proposal, independent policy review and fixed sandbox jobs.
"""
import hashlib
import json
import os
import re
import time
import urllib.error

from generic_harness_calibration import digest,require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS maintained_test_calibrations('
        'source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')


def assess_functional_red(observed,prepared):
    try:from test_first_protocol import assess_red
    except ImportError:from broker.test_first_protocol import assess_red
    output=observed['output']
    require(observed['approval'] is False and observed['output_sha256']==hashlib.sha256(output.encode()).hexdigest())
    red=assess_red(observed['exit_code'],output,prepared)
    require(not re.search(r'(?m)^ERROR:',output))
    failures=re.findall(r'(?m)^FAIL: (test_[A-Za-z0-9_]+) \(([^\n]+)\)',output)
    require(failures and all(any(method in methods and name.rsplit('/',1)[-1].removesuffix('.py') in module
        for name,methods in prepared['test_methods'].items()) for method,module in failures))
    return red


def advance(con,key,cfg,fx,*,now=None):
    now=time.time() if now is None else now
    initialize(con)
    row=con.execute('SELECT config,state FROM maintained_test_calibrations WHERE source_task=?',(key,)).fetchone()
    if row:require(json.loads(row[0])==cfg);s=json.loads(row[1])
    else:
        s=dict(stage='prepare',owner=cfg['cto'],started_at=now,source_reset=False,
            author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
        con.execute('INSERT INTO maintained_test_calibrations VALUES(?,?,?)',
            (key,json.dumps(cfg,sort_keys=True),json.dumps(s,sort_keys=True)));con.commit()
    if s['stage'] in ('blocked','red_captured'):return s
    def save(**changes):
        s.update(changes);con.execute('UPDATE maintained_test_calibrations SET state=? WHERE source_task=?',
            (json.dumps(s,sort_keys=True),key));con.commit();return s
    def hold(category):return save(stage='blocked',category=category,owner=cfg['cto'],
        required_action='CTO diagnose '+category+' with preserved jobs; no author retry, source reset or delivery approval')
    try:
        fx.verify(cfg)
        if s['stage']=='prepare':
            return save(stage='volume_create_intent',required_action='Observe exact projection volume before fixed copy')
        if s['stage']=='volume_create_intent':
            # Effects owns a separate intent journal, so this call cannot repeat
            # an uncertain Docker create after observation failure or restart.
            fx.volume(cfg)
            return save(stage='copy',required_action='Copy exact approved immutable bytes; no test execution')
        if s['stage']=='copy':
            result=fx.copy(cfg);require(type(result['exit_code']) is int and result['exit_code']==0
                and result['approval'] is False and result['output_sha256']==hashlib.sha256(result['output'].encode()).hexdigest())
            prepared=json.loads(result['output']);require(prepared==cfg['prepared'])
            return save(stage='calibration',prepared_sha256=digest(prepared),copy_result_sha256=digest(result),
                required_action='Observe ordinary native calibration of unchanged maintained test')
        if s['stage']=='calibration':
            result=fx.calibration(cfg)
            require(result.get('execution_authorized') is False and result.get('delivery_approval') is False)
            if result['stage']=='blocked':return save(calibration_stage='blocked',
                category='maintained_calibration_'+result['category'],owner=result.get('owner') or cfg['cto'],
                calibration_incident=result.get('calibration_incident'),
                required_action=result.get('required_action') or 'Observe existing CTO-owned prerequisite recovery; no identical retry')
            if result['stage']!='calibration_ready':return save(calibration_stage=result['stage'],
                category=None,owner=result.get('owner') or cfg['cto'],required_action=result.get('required_action') or
                'Observe exact native calibration prerequisite; never restart the author')
            return save(stage='red',calibration_receipt_sha256=digest(result['calibration_receipt']),
                owner=cfg['cto'],category=None,
                required_action='Execute full baseline plus same frozen NEW test; diagnostic witnesses are not Red')
        require(s['stage']=='red')
        receipt=fx.red(cfg,s)
        require(receipt['issue_id']==cfg['issue_id'] and receipt['task_id']==cfg['author_task']
            and receipt['volume']==cfg['volume'] and receipt['red']['manifest_sha256']==cfg['prepared']['manifest_sha256']
            and receipt['red']['test_sha256']==cfg['prepared']['test_sha256'])
        return save(stage='red_captured',red_receipt=receipt,
            required_action='Independent normal test/delivery admission must consume this exact Red; product route remains disabled')
    except (TimeoutError,urllib.error.URLError):return s
    except (ValueError,KeyError,TypeError):return hold('maintained_test_'+s['stage']+'_rejected')


class Effects:
    def __init__(self,b):self.b=b
    def verify(self,c):
        try:import calibration_source as source
        except ImportError:from broker import calibration_source as source
        found=source.lookup(self.b,c['issue_id']);require(found)
        cfg,s=found;proof=source.authenticate(self.b,cfg,s)
        require(proof==c['authority'] and source.qualified(self.b,c['issue_id']) is not None
            and self.b.issue_base(c['issue_id'])==c['base']
            and os.environ['BROKER_MAINTAINED_TEST_SNAPSHOT_IMAGE']==c['image'])
    def volume(self,c):
        b=self.b;name=c['volume'];tags=c['labels']
        with b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS maintained_test_volume_intents(name TEXT PRIMARY KEY,identity TEXT,state TEXT)')
            row=con.execute('SELECT identity,state FROM maintained_test_volume_intents WHERE name=?',(name,)).fetchone()
            identity=dict(Name=name,Labels=tags)
            if row:
                require(json.loads(row[0])==identity);s=json.loads(row[1])
            else:
                require(b.docker('GET','/volumes/'+name) is None)
                s=dict(stage='create_intent',started_at=time.time())
                con.execute('INSERT INTO maintained_test_volume_intents VALUES(?,?,?)',
                    (name,json.dumps(identity,sort_keys=True),json.dumps(s,sort_keys=True)));con.commit()
                b.docker('POST','/volumes/create',identity)
        actual=b.docker('GET','/volumes/'+name)
        if actual is None:
            require(time.time()-s['started_at']<600)
            raise TimeoutError('observe original maintained test volume; never repeat create')
        require(actual.get('Name')==name and actual.get('Labels')==tags)
    def copy(self,c):
        try:import test_first_job
        except ImportError:from broker import test_first_job
        payload=dict(Image=c['image'],User='10000:10000',Entrypoint=['python'],Cmd=['/maintained_test_snapshot.py'],
            NetworkDisabled=True,Env=['PYTHONDONTWRITEBYTECODE=1','MAINTAINED_TEST_SELECTION='+json.dumps(c['selection'],sort_keys=True)],
            Labels=c['labels'],HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
                SecurityOpt=['no-new-privileges'],Memory=536870912,NanoCpus=1000000000,PidsLimit=32,
                Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'},Mounts=[
                    dict(Type='volume',Source=c['base']['volume'],Target='/base',ReadOnly=True),
                    dict(Type='volume',Source=c['source_volume'],Target='/source',ReadOnly=True),
                    dict(Type='volume',Source=c['volume'],Target='/snapshot',ReadOnly=False)]))
        with self.b.db() as con:return test_first_job.run(self.b,con,c['author_task'],'copy',payload)
    def calibration(self,c):
        try:import generic_calibration_workflow as flow,generic_calibration_red_bridge as bridge,handoffs
        except ImportError:from broker import generic_calibration_workflow as flow,generic_calibration_red_bridge as bridge,handoffs
        state=flow.request(self.b,c['issue_id'],c['author_task'],engine=c['engine'])
        if state['stage']!='calibration_ready':
            with self.b.db() as con:
                route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(c['issue_id'],)).fetchone()[0])
                prior=handoffs.load(con,c['author_task'])
            # This stores only the actual prerequisite projection. It does not
            # enable the disabled route or create a task, Red or approval.
            actual=flow.Effects(self.b).plans.task(c['author_task'],c['author'])
            require(actual['status']=='completed' and actual['issue_id']==c['issue_id'])
            bridge.observe(self.b,route,actual,prior,bridge.Pending(c['issue_id'],c['author_task'],state))
            with self.b.db() as con:parent=handoffs.load(con,c['author_task'])
            projected=json.loads(parent['data']).get('calibration_incident')
            if projected:
                return {**state,'owner':projected['owner'],'calibration_incident':projected,
                    'required_action':(str(projected.get('identifier'))+': ' if projected.get('identifier') else '')+
                        projected['required_action']}
        return state
    def red(self,c,s):
        try:import generic_calibration_registration as registration,generic_calibration_gate as gate,test_first_job
        except ImportError:from broker import generic_calibration_registration as registration,generic_calibration_gate as gate,test_first_job
        from test_runner_policy import validate_argv
        prerequisite=self.calibration(c)
        require(prerequisite['stage']=='calibration_ready'
            and digest(prerequisite['calibration_receipt'])==s['calibration_receipt_sha256'])
        record=registration.register(self.b,c['issue_id'],c['author_task'])
        with self.b.db() as con:actual=gate.run(self.b,con,record)
        require(actual['receipt']==prerequisite['calibration_receipt'])
        p=c['prepared'];command=p['command'];validate_argv(command,p['test_roots'])
        payload=dict(Image=p['test_image'],User='10000:10000',Entrypoint=[command[0]],Cmd=command[1:],WorkingDir='/delivery',
            NetworkDisabled=True,Env=['PYTHONDONTWRITEBYTECODE=1'],Labels=c['labels'],
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=268435456,NanoCpus=1000000000,PidsLimit=96,
                Mounts=[dict(Type='volume',Source=c['volume'],Target='/delivery',ReadOnly=True)],
                Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'}))
        with self.b.db() as con:observed=test_first_job.run(self.b,con,c['author_task'],'red',payload)
        # Calibration passing on independent references is a prerequisite, not
        # permission to reinterpret a setup/import error as missing functionality.
        red=assess_functional_red(observed,p)
        with self.b.db() as con:
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                (c['author_task'],)).fetchall();require(len(rows)==1 and rows[0]['status']=='closed')
            binding=rows[0];require(binding['issue_id']==c['issue_id'] and binding['agent_id']==c['author'])
            old=con.execute('SELECT receipt FROM test_first_red WHERE issue_id=? OR task_id=?',
                (c['issue_id'],c['author_task'])).fetchall()
            if old:
                require(len(old)==1);receipt=json.loads(old[0][0])
                require(receipt['volume']==c['volume'] and receipt['red']==red
                    and receipt['scope']==binding['scope'] and receipt['issue_id']==c['issue_id']
                    and receipt['task_id']==c['author_task']);return receipt
            receipt=dict(issue_id=c['issue_id'],task_id=c['author_task'],scope=binding['scope'],volume=c['volume'],
                red=red,captured_at=time.time())
            con.execute('INSERT INTO test_first_red VALUES(?,?,?,?,?)',
                (c['issue_id'],c['author_task'],binding['scope'],c['volume'],json.dumps(receipt,sort_keys=True)))
        return receipt


def configuration(b,cfg,s):
    try:import calibration_source as source
    except ImportError:from broker import calibration_source as source
    authority=source.authenticate(b,cfg,s);image=os.environ.get('BROKER_MAINTAINED_TEST_SNAPSHOT_IMAGE','')
    require(bool(re.fullmatch('sha256:[a-f0-9]{64}',image)))
    base=b.issue_base(s['issue_id'])
    require(base and base['manifest_sha256']==cfg['base']['manifest_sha256'] and base['base_sha']==cfg['base']['base_sha'])
    prepared={**cfg['source']['prepared'],'manifest_sha256':authority['manifest_sha256'],'test_sha256':authority['test_sha256']}
    return dict(authority=authority,cto=cfg['cto'],author=cfg['author'],issue_id=s['issue_id'],author_task=s['author_task'],
        source_volume=s['snapshot']['volume'],volume=b.PREFIX+'-test-first-'+s['author_task'],base=base,image=image,
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.test-first-task':s['author_task'],
            'delivery-kit.maintained-source':digest(authority)},prepared=prepared,
        selection=dict(base_manifest_sha256=base['manifest_sha256'],candidate_manifest_sha256=authority['manifest_sha256'],
            test_sha256=authority['test_sha256']),engine=cfg['source'].get('calibration_engine','unittest_path_fixture_v1'))


def handle(b,key):
    try:import handoff_runtime
    except ImportError:from broker import handoff_runtime
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(key,)).fetchone()
        if not row:return None
        cfg,s=map(json.loads,row)
        if s['stage']!='maintenance_approved' or s.get('review_phase')!='escalated':return None
        c=configuration(b,cfg,s)
        with b.db() as con:state=advance(con,key,c,Effects(b))
    try:
        handoff_runtime.publish(b,dict(issue_id=s['issue_id'],enabled=True,techlead=cfg['reviewer']),
            dict(stage='maintained_test_'+state['stage'],owner=state['owner'],source_task=key,
                data=json.dumps(dict(required_action=state.get('required_action'),delivery_approval=False))))
    except Exception as error:
        # Publication is never a delivery gate or a reason to repeat effects.
        with b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS maintained_test_errors(source_task TEXT PRIMARY KEY,category TEXT)')
            con.execute('INSERT OR REPLACE INTO maintained_test_errors VALUES(?,?)',(key,'notification_'+type(error).__name__))
    return state
