"""Real paused public preparation and explicit Docker networks; no model/PR.

Checks admission, idempotence and the core Compose template. Only this fixture's
empty networks are retired by exact IDs; uncertain effects are preserved.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from prepare_hermes_project import prepare
from prepare_hermes_networks import prepare as networks
from fabriquinha.effects import write_json
from fabriquinha.executor import docker
from fabriquinha.runtime import Runtime
from fabriquinha.config import pool_subnets


def qualify(root,upstream,image,browser_image,pool):
    root=Path(root).resolve();upstream=Path(upstream).resolve()
    value=json.loads((ROOT/'examples/python-http/project.example.json').read_bytes())
    value.update(namespace='delivery-kit-network-preparation',validation_image=image,browser_image=browser_image,network_pool=pool)
    prepare(root,upstream,value,'fixture/network-preparation',19498,1,max_output_tokens=4096)
    runtime=Runtime(root,upstream);prepared=networks(root,upstream)
    assert networks(root,upstream)==prepared
    admission=runtime.check_admission(force=True)
    assert admission['ready'] and admission['missing_profiles']==[]
    assert all(state['ready'] for state in admission['profiles']['profiles'].values())
    assert runtime.status()['control']['drained'] and runtime.control.read()['paused']
    subnets=pool_subnets(pool)
    env={**os.environ,'FABRIQUINHA_INSTANCE':runtime.project.namespace,
        'FABRIQUINHA_SOURCE':str(ROOT),'FABRIQUINHA_POLICY':str(root/'provider-policy.json'),
        'FABRIQUINHA_PYTHON_IMAGE':'python@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e',
        'FABRIQUINHA_PROVIDER_PORT':'19498','FABRIQUINHA_METER_VOLUME':'delivery-kit-network-preparation-fixture-meter',
        'FABRIQUINHA_SECRET_VOLUME':'delivery-kit-network-preparation-fixture-secret',
        'FABRIQUINHA_PROJECT':runtime.project.fingerprint(),'FABRIQUINHA_CORE_SUBNET':subnets['core']}
    output=subprocess.check_output(['docker','compose','-f',str(ROOT/'examples/python-http/compose.provider.yml'),
        'config','--format','json'],env=env,text=True,timeout=20)
    compose=json.loads(output);core=compose['networks']['default']
    assert core['ipam']['config']==[{'subnet':subnets['core']}]
    assert core['labels']['fabriquinha.project']==runtime.project.fingerprint()
    write_json(root/'network-admission.json',admission)
    write_json(root/'core-compose-preflight.json',dict(name=core['name'],subnet=subnets['core'],
        labels=core['labels'],compose_render_only=True,service_started=False))
    retired=[]
    for entry in prepared['networks']:
        info=json.loads(docker('network','inspect',entry['id']))[0]
        labels=info.get('Labels') or {}
        if (info['Id']!=entry['id'] or info['Name']!=entry['name'] or info.get('Containers')
                or labels.get('fabriquinha.project')!=runtime.project.fingerprint()
                or labels.get('com.docker.compose.project')!=runtime.project.namespace+'-homologation'):
            raise RuntimeError('fixture network ownership/use changed; preserve it')
        write_json(root/('retire-network-'+entry['id']+'.json'),dict(id=entry['id'],name=entry['name'],
            project=runtime.project.fingerprint(),empty=True,subnets=info['IPAM']['Config'],state='intent'))
        docker('network','rm',entry['id'])  # Exactly once; never retry uncertain deletion.
        if entry['id'] in docker('network','ls','--no-trunc','-q').split():
            raise RuntimeError('network deletion acknowledgement uncertain; observe without repeating')
        retired.append(entry['id'])
    receipt=dict(project=runtime.project.fingerprint(),network_pool=pool,subnets=subnets,
        prepared_networks=2,ids_stable_across_replay=True,doctor_ready_before_retirement=True,
        owned_networks_retired=retired,core_compose_render_only=True,core_service_started=False,
        provider_disabled=True,operational_pause_preserved=True,model_calls=0,github_mutations=0,
        docker_jobs=0,delivery_approval=False,complete_installer=False)
    write_json(root/'receipt.json',receipt);print(json.dumps(receipt,indent=2));return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','upstream'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('image','browser-image','pool'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();qualify(args.root,args.upstream,args.image,args.browser_image,args.pool)
