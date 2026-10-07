"""Operator bootstrap for a fixed V6 diagnostic job; never author dispatch.

Run only during an idle maintenance window with the supervisor suspended.
The installed controller authenticates the experiment and reopens planning.
Subsequent planner handoffs and author admission belong to the normal supervisor.
"""
import argparse,json,re,subprocess,uuid
from pathlib import Path
from broker.template_author_executor import validate_line_qualification

RUNTIME = r'''
import broker as b,json,sys,time
from pathlib import Path
import template_line_replan as lane,harness_qualification as jobs

def main():
    value=json.load(sys.stdin);source=value['source'];qualification=value['qualification']
    from template_author_executor import validate_line_qualification
    validate_line_qualification(qualification)
    if b.IMAGE!=qualification['worker_image']:raise ValueError('installed worker drift')
    proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
    if not proxy or proxy['Image']!=qualification['proxy_image'] or not proxy['State']['Running']:
        raise ValueError('installed proxy drift')
    with b.LOCK:
        with b.db() as c:
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
                raise ValueError('active lease')
            row=c.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if not row:raise ValueError('preserved source required')
            config,state=map(json.loads,row)
            c.execute('CREATE TABLE IF NOT EXISTS template_line_experiments(source_task TEXT PRIMARY KEY,payload TEXT,state TEXT)')
            old=c.execute('SELECT receipt FROM template_registry_qualifications WHERE worker_image=?',(b.IMAGE,)).fetchone()
            if old and json.loads(old[0])!=qualification:raise ValueError('immutable qualification drift')
            if not old:c.execute('INSERT INTO template_registry_qualifications VALUES (?,?)',(b.IMAGE,json.dumps(qualification,sort_keys=True)))
            job=c.execute('SELECT payload,state FROM template_line_experiments WHERE source_task=?',(source,)).fetchone()
            first=not job
            if first:
                if state.get('stage')!='blocked' or state.get('category')!='calibration_technical_impediment' or state.get('executor'):
                    raise ValueError('exact idle technical hold required')
                experiment_root,identity,experiment=lane.experiment_for(c,config)
                if experiment['stage']!='complete':raise ValueError('executed hypothesis required')
                variant=experiment['proof']['variant_test_sha256']
                payload=lane.job_payload(b,config,variant)
                rec=dict(stage='create_intent',name=b.PREFIX+'-template-line-feasibility-'+source,at=time.time())
                c.execute('INSERT INTO template_line_experiments VALUES (?,?,?)',(source,json.dumps(payload,sort_keys=True),json.dumps(rec,sort_keys=True)))
            else:payload,rec=map(json.loads,job)
        def save():
            with b.db() as c:c.execute('UPDATE template_line_experiments SET state=? WHERE source_task=?',(json.dumps(rec,sort_keys=True),source))
        labels=b.docker('GET','/volumes/'+config['volume']).get('Labels',{})
        if (labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source
                or labels.get('delivery-kit.diagnostic-only')!='true'):raise ValueError('snapshot ownership drift')
        info=b.docker('GET','/containers/'+rec['name']+'/json')
        if not info and first:
            b.docker('POST','/containers/create?name='+rec['name'],payload)
            info=b.docker('GET','/containers/'+rec['name']+'/json')
        if not info:
            print(json.dumps(dict(stage='observe_uncertain_create_no_repost',author_retry_authorized=False)));return
        jobs.verify_job(info,payload);rec['container_id']=info['Id']
        if info['State']['Status']=='created' and rec['stage']=='create_intent':
            rec['stage']='start_intent';save()
            b.docker('POST','/containers/'+info['Id']+'/start')
            print(json.dumps(dict(stage='probe_started',container_id=info['Id'],author_retry_authorized=False)));return
        if info['State']['Running']:
            print(json.dumps(dict(stage='probe_running',container_id=info['Id'],author_retry_authorized=False)));return
        if info['State']['Status']=='created':
            print(json.dumps(dict(stage='observe_uncertain_start_no_repost',container_id=info['Id'],author_retry_authorized=False)));return
        if info['State']['Status']!='exited' or info['State']['ExitCode']!=0:raise ValueError('fixed probe failed')
        new=lane.arm(b,source,info['Id'])
        rec.update(stage='planning_reopened',receipt_sha256=new['line_recipe_reconciliation']['receipt_sha256']);save()
        print(json.dumps(dict(stage=rec['stage'],planning_stage=new['stage'],container_id=info['Id'],author_retry_authorized=False,delivery_approval=False)))

try:main()
except Exception as error:
    trace=error.__traceback__
    while trace.tb_next:trace=trace.tb_next
    print(json.dumps(dict(stage='maintenance_rejected',error_type=type(error).__name__,
        error_origin=dict(file=Path(trace.tb_frame.f_code.co_filename).name,line=trace.tb_lineno),
        author_retry_authorized=False,delivery_approval=False)))
    sys.exit(1)
'''


def read_proof(path,schema):
    path=Path(path)
    if path.stat().st_size>1048576:raise ValueError('bounded proof required')
    records=[]
    for line in path.read_text().splitlines():
        if not line.startswith('{'):continue
        try:value=json.loads(line)
        except ValueError:continue
        if value.get('schema')==schema:records.append(value)
    if len(records)!=1:raise ValueError('one exact canary receipt required')
    return records[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True)
    parser.add_argument('--source',required=True)
    parser.add_argument('--worker-image',required=True)
    parser.add_argument('--proxy-image',required=True)
    parser.add_argument('--registry-proof',required=True)
    parser.add_argument('--proxy-proof',required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',args.namespace) or str(uuid.UUID(args.source))!=args.source:
        raise ValueError('exact owned namespace and canonical source required')
    qualification=dict(schema='template-lines-v6-image-qualification-v1',status='passed',delivery_approval=False,
        worker_image=args.worker_image,proxy_image=args.proxy_image,
        registry=read_proof(args.registry_proof,'surgical-template-line-registry-probe-v6'),
        proxy=read_proof(args.proxy_proof,'template-line-proxy-image-probe-v6'))
    validate_line_qualification(qualification)
    result=subprocess.run(['docker','exec','-i','-w','/',args.namespace+'-execution-broker-1','python','-c',RUNTIME],
        input=json.dumps(dict(source=args.source,qualification=qualification)),text=True,capture_output=True,timeout=55)
    try:status=json.loads(result.stdout)
    except ValueError:raise RuntimeError('maintenance transport outcome requires observation') from None
    print(json.dumps(status))
    if result.returncode:raise RuntimeError('controller rejected maintenance; hold retained')


if __name__=='__main__':main()
