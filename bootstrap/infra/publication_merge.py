"""Fixed PR14/19 publication operations. No arbitrary PR, branch or command input."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from immutable_delivery import DeliveryStore
from pr_review_packet import load, assessment, require_read
from review_merge import current_context

REPO='codifydeep/truco-online'
BOARD=Path('/opt/data/kanban/boards/truco-online-r2-20260911')
ROOT=Path('/deliveries')
EXECUTION=Path('/opt/data/governance/execution.json')
ATTEMPT='truco-restart-20260911'
REGISTERED={14:('merge_foundation','codex/restart-baseline-20260911'),19:('merge_planning','codex/planning-v0.1-20260916'),20:('merge_reconciliation','codex/planning-reconciliation-20260917')}


def authority(card):
    number=card.get('pr_number')
    if number not in REGISTERED or card.get('integration_action')!=REGISTERED[number][0]:
        raise PermissionError('unregistered integration action')
    if (card.get('author'),card.get('reviewer'))!=('techlead','cto'):
        raise PermissionError('independent Tech Lead / CTO required')
    return number


def planning_provenance(packet,card,proof):
    if packet['pr'] not in (19,20): return
    prefix='docs/planning/v0.1/'
    names={'approvals.json','approved-brief.md','architecture.md','design.md','plan.md','stories.md'} if packet['pr']==19 else {'approvals.json','plan.md'}
    if set(packet['files'])!={prefix+n for n in names}: raise PermissionError('planning publication must contain only six reviewed documents')
    dispositions=card.get('finding_dispositions',{})
    if set(dispositions)!={'H1','H2','H3','H4'} or any(not d.get('owner') or not d.get('action') for d in dispositions.values()):
        raise PermissionError('review findings require durable owners and actions')
    manifest=json.loads(packet['files'][prefix+'approvals.json'])
    if manifest['attempt']!=ATTEMPT or manifest['brief_sha256']!='273d7760dc25b2641631a98a8d3aef352883d4a92469c145154285e9dd17d403':
        raise PermissionError('planning attempt or brief drift')
    brief=packet['files'].get(prefix+'approved-brief.md')
    if brief is not None and hashlib.sha256(brief.encode()).hexdigest()!=manifest['brief_sha256']:
        raise PermissionError('brief bytes changed')
    expected={'stories.md':('produto','techlead'),'architecture.md':('cto','techlead'),'design.md':('designer','produto'),'plan.md':('techlead','cto')}
    if len(manifest['documents'])!=4 or {d['path'] for d in manifest['documents']}!=set(expected): raise PermissionError('document set mismatch')
    store=DeliveryStore(ROOT)
    for d in manifest['documents']:
        if (d['author'],d['reviewer'])!=expected[d['path']]: raise PermissionError('review matrix mismatch')
        approval=proof.execute('SELECT 1 FROM approvals WHERE task=? AND revision=? AND review_run=? AND author=? AND reviewer=?',
            (d['task'],d['revision'],d['review_run'],d['author'],d['reviewer'])).fetchone()
        if not approval: raise PermissionError('private approval missing')
        store.load(ATTEMPT,d['task'],d['revision'])
        raw=(store.path(ATTEMPT,d['task'],d['revision'])/'files/PLAN.md').read_bytes()
        exported=packet['files'].get(prefix+d['path'])
        if (exported is not None and raw!=exported.encode()) or hashlib.sha256(raw).hexdigest()!=d['sha256']:
            raise PermissionError('export does not match private delivery')
    if packet['pr']==20:
        previous=json.loads((ROOT/'pr-review-packets/9cd74389b0ca2f5ed15e13a6fa49972016da5474ef7aa0e1cdbb2030425c106a.json').read_text())
        old=json.loads(previous['files'][prefix+'approvals.json'])
        if {d['path']:d for d in old['documents'] if d['path']!='plan.md'}!={d['path']:d for d in manifest['documents'] if d['path']!='plan.md'}:
            raise PermissionError('unchanged document provenance drift')
    receipts=proof.execute('SELECT receipt FROM publication_intents WHERE receipt IS NOT NULL').fetchall()
    if not any(json.loads(r[0]).get('pr')==(14 if packet['pr']==19 else 19) and json.loads(r[0]).get('merged') is True and json.loads(r[0]).get('merge_commit')==packet['base_sha'] for r in receipts):
        raise PermissionError('base must be integrated foundation receipt')


def validate_remote(packet,pr,ci):
    number=packet.get('pr')
    if number not in REGISTERED or packet.get('repository')!=REPO or pr.get('number')!=number:
        raise ValueError('only registered publication PR14/19')
    if pr.get('state')!='open' or pr.get('merged'):
        raise ValueError('PR is not open')
    for side,branch in [('head',REGISTERED[number][1]),('base','main')]:
        if (pr[side]['sha']!=packet[side+'_sha'] or pr[side]['ref']!=branch
            or packet[side+'_branch']!=branch or pr[side]['repo']['full_name']!=REPO):
            raise ValueError('stale or foreign head/base')
    if (ci.get('headSha'),ci.get('status'),ci.get('conclusion'),ci.get('event'))!=(packet['head_sha'],'completed','success','pull_request'):
        raise ValueError('exact real pull_request CI required')


def gh(*args):
    env=dict(os.environ,GH_CONFIG_DIR='/opt/data/home/.config/gh')
    return json.loads(subprocess.check_output(['gh',*args],env=env,text=True,timeout=25))


def policy_preflight():
    repo=gh('api',f'repos/{REPO}')
    protection=gh('api',f'repos/{REPO}/branches/main/protection')
    rules=gh('api',f'repos/{REPO}/rules/branches/main')
    return validate_policy(repo,protection,rules)


def validate_policy(repo,protection,rules):
    if repo.get('allow_merge_commit') is not True or protection.get('required_linear_history',{}).get('enabled') is not False:
        raise PermissionError('publication_policy_conflict: merge commit requires non-linear history')
    if any(r.get('type')=='required_linear_history' for r in rules):
        raise PermissionError('publication_policy_conflict: ruleset requires linear history')
    checks=protection.get('required_status_checks',{})
    if not protection.get('enforce_admins',{}).get('enabled') or not checks.get('strict') or not {'governance','hermes-independent-review'} <= set(checks.get('contexts',[])):
        raise PermissionError('publication_policy_conflict: required review/CI protections missing')
    if protection.get('allow_force_pushes',{}).get('enabled') is not False or protection.get('allow_deletions',{}).get('enabled') is not False:
        raise PermissionError('publication_policy_conflict: destructive operations allowed')
    return dict(passed=True,repository=REPO,branch='main',merge_method='merge',required_linear_history=False)


def context(task,run,revision,claim):
    state=json.loads(EXECUTION.read_text())
    if state['attempt']!=ATTEMPT or state['product_dispatch_enabled'] or state['implementation_dispatch_enabled']:
        raise PermissionError('wrong execution scope')
    if (BOARD/'MAINTENANCE').exists() or (BOARD/'READ_ONLY').exists(): raise PermissionError('board paused')
    config=json.loads((ROOT/'planning-config.json').read_text())
    if config['attempt']!=state['attempt']: raise PermissionError('attempt drift')
    if config!=json.loads((BOARD/'planning.json').read_text()): raise PermissionError('configuration drift')
    card=config['cards'][task]
    authority(card)
    current_context(BOARD/'kanban.db',task,'cto',run)
    with sqlite3.connect((BOARD/'kanban.db').as_uri()+'?mode=ro',uri=True) as board:
        if board.execute('SELECT claim_lock FROM tasks WHERE id=?',(task,)).fetchone()[0]!=claim:
            raise PermissionError('stale claim')
    with sqlite3.connect((ROOT/'controller.db').as_uri()+'?mode=ro',uri=True) as proof:
        proof.row_factory=sqlite3.Row
        intent=proof.execute('SELECT payload FROM publication_intents WHERE task=? AND run=? AND revision=?',(task,run,revision)).fetchone()
        if not intent or json.loads(intent['payload'])['claim']!=claim: raise PermissionError('missing durable intent')
        latest=proof.execute('SELECT * FROM deliveries WHERE task=? ORDER BY run DESC LIMIT 1',(task,)).fetchone()
        if not latest or latest['revision']!=revision or latest['author']!='techlead' or latest['reviewer']!='cto':
            raise PermissionError('stale delivery')
        validation=proof.execute('SELECT passed FROM validations WHERE task=? AND revision=? AND review_run=?',(task,revision,run)).fetchone()
        if not validation or not validation[0]: raise PermissionError('no validation in this review run')
        packet=load(ROOT,card)
        planning_provenance(packet,card,proof)
        require_read(proof,task,run,card,packet)
    store=DeliveryStore(ROOT); store.load(state['attempt'],task,revision)
    folder=store.path(state['attempt'],task,revision)/'files'
    if hashlib.sha256((folder/'PR-PACKET.json').read_bytes()).hexdigest()!=card['packet_sha256']:
        raise PermissionError('frozen packet changed')
    if assessment((folder/'PLAN.md').read_text(),packet)['decision']!='approve':
        raise PermissionError('assessment requests changes; merge forbidden')
    return packet


def perform(controller,card,request,revision):
    number=authority(card)
    task,review=controller.current(request)
    if not review or task['assignee']!='cto': raise PermissionError('live CTO review required')
    controller.db.execute('CREATE TABLE IF NOT EXISTS publication_intents(task TEXT,run INTEGER,revision TEXT,payload TEXT,receipt TEXT,PRIMARY KEY(task,run,revision))')
    identity=(task['id'],request['run'],revision)
    controller.db.execute('INSERT OR IGNORE INTO publication_intents(task,run,revision,payload) VALUES(?,?,?,?)',
        (*identity,json.dumps(dict(claim=request['claim'],action=card['integration_action']))))
    controller.db.commit()
    from review_controller import bounded_run
    from publication_access import preflight,container_command,record_failure
    proof=preflight(controller,task['id'])
    if not proof.get('passed'):
        error='publication access preflight failed: '+proof.get('error','unknown')
        record_failure(controller,task['id'],request['run'],revision,error,proof)
        raise PermissionError(error)
    command=container_command(controller,task['id'])+['--run',str(request['run']),
        '--revision',revision,'--claim',request['claim']]
    try:
        result=bounded_run(command,timeout=100,limit=65536)
        if result.returncode: raise RuntimeError('fixed publication executor failed: '+result.stdout[-4000:])
    except Exception as error:
        record_failure(controller,task['id'],request['run'],revision,error,proof)
        raise
    receipt=json.loads(result.stdout)
    if (not receipt.get('merged') or receipt.get('head')!=card['head_sha'] or receipt.get('revision')!=revision
        or receipt.get('task')!=task['id'] or receipt.get('review_run')!=request['run']
        or receipt.get('pr')!=number or receipt.get('base')!=card['base_sha']
        or not re.fullmatch(r'[0-9a-f]{40}',receipt.get('merge_commit',''))):
        raise ValueError('invalid publication receipt')
    controller.db.execute('UPDATE publication_intents SET receipt=? WHERE task=? AND run=? AND revision=?',
        (json.dumps(receipt),*identity)); controller.db.commit()
    return receipt


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--task',required=True); parser.add_argument('--run',type=int)
    parser.add_argument('--revision'); parser.add_argument('--claim')
    parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--policy-preflight',action='store_true')
    args=parser.parse_args()
    import signal
    signal.alarm(30 if args.preflight else 85)
    if args.policy_preflight:
        print(json.dumps(policy_preflight())); return
    if args.preflight:
        from publication_access import check_access
        print(json.dumps(check_access(args.task))); return
    if not args.run or not args.revision or not args.claim: parser.error('live run, revision and claim required')
    check=lambda: context(args.task,args.run,args.revision,args.claim)
    packet=check()
    number=packet['pr']
    pr=gh('api',f'repos/{REPO}/pulls/{number}')
    def receipt(remote):
        if remote['head']['sha']!=packet['head_sha']: raise ValueError('merged foreign head')
        commit=gh('api',f'repos/{REPO}/git/commits/'+remote['merge_commit_sha'])
        if [p['sha'] for p in commit['parents']]!=[packet['base_sha'],packet['head_sha']]:
            raise ValueError('merged commit has unexpected parents')
        return dict(merged=True,pr=number,head=packet['head_sha'],base=packet['base_sha'],
                    merge_commit=remote['merge_commit_sha'],task=args.task,review_run=args.run,revision=args.revision)
    if pr.get('merged'):
        print(json.dumps(receipt(pr))); return
    run_id=packet['ci']['url'].rsplit('/',1)[-1]
    if not re.fullmatch(r'[0-9]+',run_id): raise ValueError('invalid CI identity')
    ci=gh('run','view',run_id,'--repo',REPO,'--json','headSha,status,conclusion,event,jobs')
    validate_remote(packet,pr,ci)
    if number in (19,20):
        files=gh('api',f'repos/{REPO}/pulls/{number}/files?per_page=100')
        count=6 if number==19 else 2
        if pr.get('changed_files')!=count or len(files)!=count or {f['filename'] for f in files}!=set(packet['files']) or any(f['status']!=('added' if number==19 else 'modified') for f in files):
            raise PermissionError('remote planning diff exceeds six new documents')
    if not any(step['name']=='Proteger testes existentes' and step['conclusion']=='success'
        for job in ci['jobs'] for step in job['steps']): raise ValueError('trusted PR guard did not run')
    protection=gh('api',f'repos/{REPO}/branches/main/protection')
    if not protection['enforce_admins']['enabled'] or not protection['required_status_checks']['strict']:
        raise PermissionError('strict protected base required')
    if 'governance' not in protection['required_status_checks']['contexts']: raise PermissionError('missing CI gate')
    policy_preflight()
    if pr['draft']:
        check()
        gh('api','graphql','-f','query=mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{id}}}',
           '-f','id='+pr['node_id'])
    check(); validate_remote(packet,gh('api',f'repos/{REPO}/pulls/{number}'),ci)
    # This status is emitted only by the fixed executor under a live CTO review claim.
    gh('api','--method','POST',f'repos/{REPO}/statuses/'+packet['head_sha'],
       '-f','state=success','-f','context=hermes-independent-review',
       '-f',f'description=CTO {args.task} run {args.run}; immutable review validated')
    check(); validate_remote(packet,gh('api',f'repos/{REPO}/pulls/{number}'),ci)
    policy_preflight()
    merged=gh('api','--method','PUT',f'repos/{REPO}/pulls/{number}/merge','-f','sha='+packet['head_sha'],'-f','merge_method=merge')
    if not merged.get('merged'): raise ValueError('GitHub refused merge')
    print(json.dumps(receipt(gh('api',f'repos/{REPO}/pulls/{number}'))))


if __name__=='__main__': main()
