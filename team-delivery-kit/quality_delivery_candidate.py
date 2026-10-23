"""Trusted local controller bridge: native capture → export → exact Git proof.

No public/worker endpoint or agent-supplied packet, command, repository identity,
test selection, push, merge or Green approval. Repository path is operator config.
Existing child journals reconcile restarts; no new identity is minted on resume.
"""
from pathlib import Path
import re
import quality_delivery_export as exporter
import quality_git_candidate as candidate
from broker import quality_candidate_binding as binding

require=binding.require


def repository(repo,expected):
    repo=Path(repo)
    require(repo.is_absolute() and repo.resolve()==repo and repo.is_dir()
        and isinstance(expected,str) and re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',expected))
    candidate.binding.repository_policy(repo)
    remote=candidate.binding.git(repo,'config','--get','remote.origin.url').decode().strip()
    require(remote in ('https://github.com/'+expected,'https://github.com/'+expected+'.git',
        'git@github.com:'+expected,'git@github.com:'+expected+'.git'))
    return repo


def advance(b,request,repo,private,*,effects=None):
    binding.delivery.admission.enabled(b)
    with b.db() as con:
        if binding.maintenance.current(con):raise binding.validation_job.Pending('maintenance pauses local candidate bridge')
    previous=binding.load(b,request)
    if previous:
        identity,receipt=previous
        require(str(Path(repo))==identity['repository'])
        return receipt
    packet=binding.delivery.candidate_packet(b,request);d=packet['descriptor']
    repo=repository(repo,packet['repository'])
    exported=exporter.export(d,private,effects=effects)
    require(exported['descriptor_sha256']==binding.quality.digest(d) and exported['stage']=='exported')
    proof=candidate.materialize(repo,Path(exported['directory']),d['manifest_sha256'],packet['plan'],
        packet['frozen_tests'],request,d['task_id'],private)
    return binding.record(b,request,packet,str(repo),proof)


def advance_remote(authority,request,repo,private,*,effects=None):
    """Operator-configured local authority; never a model-provided RPC target."""
    observed=authority.inspect(request)
    if observed['stage']=='bound':
        identity,receipt=observed['identity'],observed['receipt'];binding.validate(identity,receipt)
        require(str(Path(repo))==identity['repository'] and identity['request_id']==request
            and identity['namespace']==authority.namespace)
        return receipt
    require(observed['stage']=='pending');packet=observed['packet'];d=packet['descriptor']
    require(d['request_id']==request and d['namespace']==authority.namespace)
    repo=repository(repo,packet['repository'])
    exported=exporter.export(d,private,effects=effects)
    require(exported['descriptor_sha256']==binding.quality.digest(d) and exported['stage']=='exported')
    proof=candidate.materialize(repo,Path(exported['directory']),d['manifest_sha256'],packet['plan'],
        packet['frozen_tests'],request,d['task_id'],private)
    result=authority.record(request,packet,str(repo),proof)
    identity,receipt=result['identity'],result['receipt'];binding.validate(identity,receipt)
    require(identity['packet']==packet and identity['repository']==str(repo) and receipt['candidate']==proof
        and identity['namespace']==authority.namespace)
    return receipt
