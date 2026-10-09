"""Read-only native provenance for controller-owned memory nominations/reviews."""
import hashlib
import json
import re
import subprocess
import time
import uuid
import sqlite3
from contextlib import closing

PROGRAM='''import broker as b,json,sys
with b.db() as c:
 rows=c.execute("SELECT n.task_id,n.agent_id,n.issue_id,n.scope,g.mode,l.status AS lease_status FROM native_bindings n JOIN grants g USING(request_id) JOIN leases l USING(request_id) WHERE n.task_id=?",(sys.argv[1],)).fetchall()
 print(json.dumps([dict(r) for r in rows]))
'''


def observe(task,agent,namespace,cli):
    for value in (task,agent):
        if str(uuid.UUID(value))!=value:raise ValueError('canonical native identity required')
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace):raise ValueError('owned instance required')
    broker=namespace+'-execution-broker-1'
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',broker],text=True,timeout=10))
    if labels.get('com.docker.compose.project')!=namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('owned memory provenance controller required')
    rows=json.loads(subprocess.check_output(['docker','exec','-w','/',broker,'python','-c',PROGRAM,task],text=True,timeout=15))
    if (len(rows)!=1 or rows[0]['task_id']!=task or rows[0]['agent_id']!=agent
            or rows[0]['mode']!='planning' or rows[0]['lease_status']!='closed'
            or ':planning:' not in rows[0]['scope']):
        raise ValueError('exact closed native planning binding required')
    runs=[r for r in cli('runs',rows[0]['issue_id']) if r.get('id')==task]
    if len(runs)!=1 or runs[0].get('agent_id')!=agent or runs[0].get('status')!='completed':
        raise ValueError('native memory source not completed')
    output=(runs[0].get('result') or {}).get('output')
    if not isinstance(output,str) or not 1<=len(output)<=7000:
        raise ValueError('bounded complete native memory output required')
    return {'task_id':task,'agent_id':agent,'status':'completed','mode':'planning',
        'lease_status':'closed','content_sha256':hashlib.sha256(output.encode()).hexdigest()},output


def nominate_cto(private,repository,namespace,ledger,agent,cli,*,now=None):
    """Nominate the exact native CTO decisions; never fabricate or approve them."""
    from decision_memory import nominate
    from planning_intake import parse_proposal
    if ledger.get('stage')!='plan_ready' or not ledger.get('configuration_sha256'):
        raise ValueError('completed configured planning source required')
    source=ledger['outputs']['cto']
    native,output=observe(source['task_id'],agent,namespace,cli)
    proposal=parse_proposal(output,'cto')
    if native['content_sha256']!=source['content_sha256'] or proposal!=source['proposal']:
        raise ValueError('native CTO source differs from accepted planning record')
    now=int(time.time()) if now is None else now
    entry={'subject':'Architecture decisions from '+ledger['name'],
        'decisions':proposal['technical_decisions'],'commit':ledger['base_sha'],
        'source_release':ledger['name'],'expires':now+30*86400,'supersedes':None}
    # Resuming nomination does not renew validity or create another request.
    from decision_memory import path
    database=path(private)
    if database.exists():
        with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as con:
            rows=con.execute('SELECT id,envelope FROM recommendations WHERE repository=? AND namespace=?',
                (repository,namespace)).fetchall()
        for key,encoded in rows:
            old=json.loads(encoded)
            if old['source']['task_id']!=native['task_id']:continue
            expected={**entry,'expires':old['entry']['expires']}
            from delivery_memory import digest
            if (old['source']!=native or old['entry']!=expected
                    or digest(encoded.encode())!=key):raise ValueError('native nomination identity drift')
            return key
    return nominate(private,repository,namespace,entry,native,now=now)


def curate_native(private,repository,namespace,key,task,reviewer,cli):
    from decision_memory import curate
    native,output=observe(task,reviewer,namespace,cli)
    answer=json.loads(output)
    return curate(private,repository,namespace,key,answer,native)
