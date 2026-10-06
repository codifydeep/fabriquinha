"""Operator-only read-only Git/GitHub capture for the registered publication PR."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

REPO='codifydeep/truco-online'
CHECKOUT='/Users/weber/Documents/projetos_pessoais_desenv/hermes/truco-online'


def run(*args):
    return subprocess.check_output(args, text=True, cwd=CHECKOUT, timeout=90)


def git(*args):
    return run('git','-c','safe.directory='+CHECKOUT,*args)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--head', required=True)
    parser.add_argument('--ci-run', required=True)
    parser.add_argument('--pr', type=int, choices=(14,19,20), default=19)
    args=parser.parse_args()
    pr=json.loads(run('gh','api','repos/'+REPO+'/pulls/'+str(args.pr)))
    head=pr['head']['sha']; base=pr['base']['sha']
    assert pr['state']=='open' and pr['draft'] and pr['head']['repo']['full_name']==REPO
    assert pr['base']['ref']=='main'
    assert head==args.head
    ci=json.loads(run('gh','run','view',args.ci_run,'--repo',REPO,'--json','headSha,status,conclusion,event,url'))
    assert ci['headSha']==head and ci['status']=='completed' and ci['conclusion']=='success'
    assert ci['event']=='pull_request'
    names=git('diff','--name-only',base,head).splitlines()
    assert names and '.github/workflows/quality-gates.yml' not in names
    files={name:git('show',head+':'+name) for name in names}
    with tempfile.TemporaryDirectory(prefix='pr-trusted-guard-') as tmp:
        guard=Path(tmp)/'guard.sh'
        guard.write_text(git('show',base+':scripts/ci/test-integrity-guard.sh'))
        env=dict(os.environ,GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=CHECKOUT)
        proof=subprocess.run(['bash',str(guard),base,head],cwd=CHECKOUT,env=env,text=True,capture_output=True,check=True)
    packet=dict(repository=REPO,pr=args.pr,head_sha=head,base_sha=base,head_branch=pr['head']['ref'],
        base_branch=pr['base']['ref'],diff=git('diff','--no-ext-diff',base,head),files=files,
        base_governance={p:git('show',base+':'+p) for p in ('AGENTS.md','scripts/ci/test-integrity-guard.sh','.github/workflows/quality-gates.yml')},
        ci=ci,trusted_guard_passed=True,trusted_guard_output=proof.stdout,
        limitations=(['Real pull_request CI passed against integrated main; trusted base guard also executed separately.',
          'Foundation and original planning are integrated; this assessment covers only the registered publication head/base.'] if args.pr!=14 else
          ['Foundation scope only: inspect all contracts, model templates, CI changes and safety boundaries.',
           'Real pull_request CI passed; no automatic approval or merge.',
           'Planning export is not in foundation. Snapshot fixtures are tests, not a new brief approval.'])+
          ['Historical Qwen-only contract is superseded only for model choice by explicit CEO authorization of DeepSeek.',
           'No implementation, release or merge authorization.'])
    current=json.loads(run('gh','api','repos/'+REPO+'/pulls/'+str(args.pr)))
    assert current['head']['sha']==head and current['base']['sha']==base and current['state']=='open'
    raw=(json.dumps(packet,ensure_ascii=False,indent=2)+'\n').encode()
    # Foundation includes nine complete configs and SOULs, unlike documentary PR19.
    # Pagination remains bounded at 8000 characters; never truncate source evidence.
    limit=600000 if args.pr==14 else 250000
    assert len(raw)<limit, f'packet too large ({len(raw)} bytes); split the review scope, never truncate'
    path=Path('/tmp/pr-review-packet.json'); path.write_bytes(raw); path.chmod(0o600)
    print(json.dumps(dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),head=head,base=base,bytes=len(raw))))


if __name__=='__main__': main()
