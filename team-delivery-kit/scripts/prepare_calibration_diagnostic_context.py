"""Local complete-context preparation from actual diagnostic read requests.

This deliberately does not import the proxy transport or send model requests.
Input must be freshly exported by the controller after ownership validation.
"""
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from calibration_diagnostic_probe import build,attach_dependencies,prepared_identity
from calibration_response_contract import safe_path
from calibration_diagnostic_runner import command,save,reader_code,IMAGE
from docker_grouping import args as group_args


def main():
    experiment=sys.argv[1]
    if str(uuid.UUID(experiment))!=experiment:raise ValueError('exact experiment identity required')
    root=Path(__file__).resolve().parents[1]/'.local-port2'/'diagnostic-probes'/experiment
    if sys.argv[2:]==['--qualify-prepared']:
        body=json.loads((root/'prepared-request.json').read_text())
        parent=json.loads((root/'prepared-identity.json').read_text())
        receipt=prepared_identity(body,parent)
        save(root,'prepared-context-receipt.json',receipt)
        print(json.dumps(dict(prepared_context_qualified=True,paid_calls=0,
            input_sha256=receipt['input_sha256'],workflow_transition=False)))
        return
    if sys.argv[2:]:raise ValueError('unknown diagnostic preparation operation')
    source=json.load(sys.stdin)
    result=json.loads((root/'result.json').read_text())
    identity=result['experiment']
    body,receipt=build(source['note'],source['reads'],'anthropic/claude-haiku-5.5',
        str(uuid.uuid4()),source['source_task'])
    if receipt['source_sha256']!=identity['source_sha256'] or receipt['source_task']!=identity['source_task']:
        raise ValueError('diagnostic source drift')
    paths=sorted({r['path'] for e in result['events'] for r in e.get('requested_reads',[])})
    if not 1<=len(paths)<=16 or any(not safe_path(p,'bundle') for p in paths):
        raise ValueError('bounded actual requested dependency paths required')
    dependencies=[]
    for role in ('candidate','previous'):
        selected=[p for p in paths if p.split('/')[2]==role]
        if not selected:continue
        volume=source[role+'_volume']
        if not re.fullmatch(r'delivery-kit-port2-test-first-[a-f0-9-]{36}',volume):
            raise ValueError('owned test-first snapshot required')
        name='delivery-kit-port2-context-'+receipt['experiment_id'][:8]+'-'+role
        manifest=source['candidate_manifest_sha256'] if role=='candidate' else None
        save(root,'complete-'+role+'-intent.json',dict(container=name,volume=volume,
            paths=selected,manifest_sha256=manifest,image=IMAGE,paid_calls=0))
        dependencies.extend(command(['docker','run','--rm','--name',name,
            *group_args('calibration-context','delivery-kit-port2'),
            '--label','delivery-kit.diagnostic-experiment='+receipt['experiment_id'],
            '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--memory','128m','--cpus','0.5','--pids-limit','32','--mount',
            'type=volume,src='+volume+',dst=/evidence/'+role+',readonly',
            '-i','--entrypoint','python',IMAGE,'-I','-S','-B','-c',reader_code('complete')],
            dict(paths=selected,manifest=manifest),30))
    prepared=attach_dependencies(body,dependencies)
    save(root,'complete-dependencies.json',dependencies)
    save(root,'prepared-request.json',prepared)
    save(root,'prepared-identity.json',receipt)
    save(root,'prepared-context-receipt.json',prepared_identity(prepared,receipt))
    print(json.dumps(dict(dependency_files=len(dependencies),
        dependency_pages=sum(len(d['pages']) for d in dependencies),
        dependency_lines=sum(d['total_lines'] for d in dependencies),
        request_bytes=len(json.dumps(prepared).encode()),paid_calls=0,
        native_read_evidence=False,execution_authorized=False,delivery_approval=False,
        workflow_transition=False)))


if __name__=='__main__':
    try:main()
    except Exception:
        print(json.dumps(dict(preparation_failed=True,automatic_replay=False,paid_calls=0)))
        sys.exit(1)
