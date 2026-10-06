"""Operator qualification of existing fixed adapters. No model authorization."""
import json
from pathlib import Path
from product_workspace import digest

def prepare():
    from product_autonomy import Coordinator,api,atomic
    c=Coordinator();head=api('git/ref/heads/release/v0.1')['object']['sha']
    pubs=[json.loads(r[0]) for r in c.db.execute("SELECT value FROM records WHERE key LIKE 'publication:%'")]
    latest=next(iter(sorted((p for p in pubs if p['state']=='INTEGRATED'),key=lambda p:p['pr'],reverse=True)),None)
    if not latest:raise PermissionError('integrated exact-base source required')
    card=c.cfg['cards'][latest['source_task']]
    packet=dict(head=head,files=c.source_files(head),image=card['validation_image'],integration=latest)
    atomic(c.root/'adapter-qualification.json',packet)
    print(json.dumps(dict(head=head,image=packet['image'],source_sha256=digest(packet['files']))))

def execute():
    from product_docker_runner import DockerRunner
    from product_autonomy import atomic
    from product_case_inventory import inventory
    root=Path('/control');cfg=json.loads((root/'config.json').read_text());packet=json.loads((root/'adapter-qualification.json').read_text())
    result=DockerRunner(cfg['snapshot_root'],'lobby-ts')(packet['files'],packet['image'])
    if result['exit_code']!=0:raise PermissionError('full-project baseline qualification failed: '+result['output'][-4000:])
    proof=dict(head=packet['head'],image=packet['image'],source_sha256=digest(packet['files']),cases=inventory(result),result=result)
    atomic(root/'adapter-qualification-receipt.json',proof)
    print(json.dumps(dict(passed=True,head=proof['head'],cases=len(proof['cases']),receipt=digest(proof))))

def activate():
    from product_autonomy import Coordinator,api,atomic
    from product_recovery import CONFIGS
    from product_policy import CAPABILITIES
    c=Coordinator();packet=json.loads((c.root/'adapter-qualification.json').read_text());proof=json.loads((c.root/'adapter-qualification-receipt.json').read_text())
    head=api('git/ref/heads/release/v0.1')['object']['sha']
    if head!=packet['head'] or head!=proof['head'] or not proof['result']['passed'] or digest(packet['files'])!=proof['source_sha256'] or packet['image']!=proof['image']:raise PermissionError('qualification drift')
    for cap in ('backend','quality','design','product'):
        c.cfg.setdefault('enabled_capabilities',{})[cap]=dict(adapter=CAPABILITIES[cap]['adapter'],image=proof['image'],validated_receipt=digest(proof),config_commit=head,config_sha256=digest({n:packet['files'][n] for n in CONFIGS}))
    # Parallel scheduling stays separately gated until safe integration validation.
    c.cfg['dag_planning']=True
    atomic(c.root/'config.json',c.cfg);atomic(c.board/'product-adapter.json',c.cfg)
    print(json.dumps(dict(capabilities=list(c.cfg['enabled_capabilities']),dag_planning=True,dispatch_slots=c.cfg['dispatch_slots'])))

if __name__=='__main__':
    import sys
    {'prepare':prepare,'execute':execute,'activate':activate}[sys.argv[1]]()
