"""Operator bootstrap of a NEW non-primary branch, never a product delivery.

Retains history via an ordinary child commit with a fixed infrastructure seed.
No force push, model, arbitrary product files, runner or main protection changes.
Lost acknowledgements are observed through the existing controller journal.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.artifacts import digest
from fabriquinha.effects import EffectBlocked,Journal,write_json
from fabriquinha.publication import GitHub,Repository
from fabriquinha.runtime import Runtime


def bootstrap(runtime):
    project,store=runtime.project,runtime.store
    if (project.qualification or not project.local_ci or not project.delivery_roles
            or not project.branch.startswith('release/') or not runtime.control.read()['paused']):
        raise ValueError('paused real installation with explicit local CI and new release branch required')
    status=runtime.status()
    if status['cards'] or not status['control'].get('drained'):
        raise ValueError('bootstrap requires an empty board with no live workers or unsettled effects')
    actor=project.delivery_roles['integration'];repo=Repository(project,store,assignee=actor);github=GitHub(project,actor)
    if json.loads(github.cli('api','user')).get('login','').lower()!=project.local_ci['publisher'].lower():
        raise ValueError('explicit CI publisher account required for branch bootstrap')
    folder=store.root/'bootstrap';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=folder/'inputs.json';journal=Journal(store.root/'effects')
    with journal.lock('bootstrap:'+project.fingerprint()):
        if not path.exists():
            if repo.remote_head(project.branch) is not None:raise ValueError('existing branches must never be bootstrapped')
            repo.git('fetch','--no-tags','origin','refs/heads/main')
            base=repo.remote_head('main')
            main=json.loads(github.cli('api',f'repos/{github.repo}/branches/main/protection'))
            write_json(path,dict(project=project.fingerprint(),base=base,main_protection=main,
                snapshot=store.capture(ROOT/'examples/python-http/bootstrap')))
        inputs=json.loads(path.read_bytes())
        if inputs['project']!=project.fingerprint():raise ValueError('bootstrap project drift')
        identity={key:inputs[key] for key in ('project','base','snapshot')}
        branch='bootstrap/fabriquinha-'+project.fingerprint()[:20]
        head=repo.propose(inputs['snapshot'],inputs['base'],branch,'infrastructure-bootstrap')
        def observed():
            current=repo.remote_head(project.branch)
            if current is not None and current!=head:raise EffectBlocked('new branch diverged; preserve it')
            return {'head':head} if current==head else None
        def push():
            if repo.remote_head(project.branch) is not None:raise EffectBlocked('new branch already exists')
            repo.push(project.branch,head);return observed()
        journal.do('bootstrap-branch:'+project.fingerprint(),identity,push,observed)
        policy=dict(required_status_checks=dict(strict=True,checks=[dict(context=project.local_ci['context'],app_id=-1)]),
            enforce_admins=True,required_pull_request_reviews=dict(dismiss_stale_reviews=True,
                require_code_owner_reviews=False,required_approving_review_count=0),restrictions=None,
            required_linear_history=False,allow_force_pushes=False,allow_deletions=False,
            required_conversation_resolution=True)
        endpoint=f'repos/{github.repo}/branches/{quote(project.branch,safe="")}/protection'
        def protected():
            value=json.loads(github.cli('api',endpoint));checks=value.get('required_status_checks') or {}
            required=checks.get('checks')
            if (not isinstance(required,list) or len(required)!=1
                    or required[0].get('context')!=project.local_ci['context'] or required[0].get('app_id') not in (None,-1)
                    or checks.get('strict') is not True
                    or value.get('enforce_admins',{}).get('enabled') is not True
                    or value.get('required_pull_request_reviews',{}).get('dismiss_stale_reviews') is not True
                    or value.get('required_pull_request_reviews',{}).get('required_approving_review_count')!=0
                    or value.get('allow_force_pushes',{}).get('enabled') is not False
                    or value.get('allow_deletions',{}).get('enabled') is not False
                    or value.get('required_conversation_resolution',{}).get('enabled') is not True):
                raise EffectBlocked('bootstrap protection differs from the approved new-branch contract')
            return dict(head=head,policy=digest(policy))
        def protect():
            github.cli('api','--method','PUT',endpoint,'--input','-',data=json.dumps(policy))
            return protected()
        journal.do('bootstrap-protection:'+project.fingerprint(),{**identity,'policy':policy},protect,protected)
        protected()  # Never trust only a cached mutation ACK.
        if repo.remote_head('main')!=inputs['base'] or json.loads(github.cli(
                'api',f'repos/{github.repo}/branches/main/protection'))!=inputs['main_protection']:
            raise EffectBlocked('main changed during bootstrap; inspect independently, never overwrite it')
        result=dict(project=project.fingerprint(),branch=project.branch,head=head,parent=inputs['base'],
            snapshot=inputs['snapshot'],main_unchanged=True,protection_verified=True,
            product_delivery=False,delivery_approval=False,model_calls=0)
        write_json(folder/'receipt.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(bootstrap(Runtime(args.root,args.upstream)),indent=2))
