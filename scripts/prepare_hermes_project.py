"""Prepare a fresh, paused Hermes project without inference or external writes.

This is not a complete installer: provide the pinned upstream/SDK and cached
validator/browser images. CI, GitHub branch/protection and relay provisioning
are separate explicit operations. Never copy an old home, database or key.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.provider import Policy
from fabriquinha.runtime import Runtime,bind
from fabriquinha.kanban_lane import native


def configuration(value,model,port,max_calls):
    project=Project.parse(value)
    if (project.qualification or not project.technical_roles or not project.coordination_roles or not project.delivery_roles
            or project.branch in ('main','master') or type(port) is not int or not 1024<=port<=65535):
        raise ValueError('real isolated delivery project, non-primary branch and explicit loopback port required')
    policy=Policy.parse(dict(version=1,project=project.fingerprint(),model=model,max_calls=max_calls,
        max_output_tokens=4096,enabled=False,client_token=secrets.token_urlsafe(32)))
    profiles=set(project.reviewers)
    for author in project.reviewers:profiles.update(project.reviewers_for(author))
    for roles in (project.technical_roles,project.coordination_roles,project.delivery_roles):profiles.update(roles.values())
    return project,policy,sorted(profiles)


def prepare(root,upstream,value,model,port,max_calls):
    root,upstream=Path(root).absolute(),Path(upstream).resolve()
    project,policy,profiles=configuration(value,model,port,max_calls)
    if root.exists() or root.is_symlink():raise ValueError('fresh root required; existing installations must not be overwritten')
    if root.resolve().is_relative_to(ROOT) and subprocess.run(
            ['git','-C',str(ROOT),'check-ignore','--quiet',str(root.resolve())],capture_output=True).returncode:
        raise ValueError('installation inside the source checkout must use a Git-ignored private root')
    bind(root,upstream)  # Verify pristine pinned upstream before creating anything.
    root.mkdir(mode=0o700,parents=True)
    write_json(root/'project.json',value)
    runtime=Runtime(root,upstream)
    runtime.control.pause()  # Fence before profiles/routes exist; never start dispatch here.
    kb,kbc,_=native()
    with kbc.connect_closing() as conn:
        if conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]:raise ValueError('new project board must be empty')
    from hermes_cli.profiles import create_profile,profile_exists
    for name in profiles:
        if profile_exists(name):raise ValueError('fresh profile home required; never reuse active context')
        create_profile(name,no_skills=True,description='Prepared isolated delivery profile; no gateway enabled')
        write_json(root/'home/profiles'/name/'config.yaml',dict(model={'streaming':False,'context_length':65536},
            auxiliary={'title_generation':{'enabled':False}},tools={'tool_search':{'enabled':'off'}},
            terminal={'backend':'fabriquinha','cwd':'/workspace'}))
    write_json(root/'provider-policy.json',policy.values())
    write_json(root/'route.json',dict(base_url='http://127.0.0.1:'+str(port)+'/v1',api_key=policy.client_token,
        provider='custom',api_mode='chat_completions',model=policy.model))
    result=dict(prepared=True,project=project.fingerprint(),profiles=profiles,empty_board=True,
        operational_pause=True,provider_enabled=False,service_started=False,model_calls=0,
        github_mutations=0,delivery_approval=False,complete_installer=False)
    write_json(root/'preparation.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--model',required=True)
    parser.add_argument('--provider-port',type=int,required=True);parser.add_argument('--max-calls',type=int,required=True)
    args=parser.parse_args();path=args.project
    if not path.is_file() or path.stat().st_size>16384:raise ValueError('bounded project configuration required')
    print(json.dumps(prepare(args.root,args.upstream,json.loads(path.read_bytes()),args.model,args.provider_port,args.max_calls),indent=2))
