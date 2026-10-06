"""Operator bridge: exact native approval, protected merge, durable observation.

No agent input, protection exception, deployment or historical TDD admission.
An uncertain GitHub mutation is observed, never blindly dispatched again.
"""
import argparse
import json
import re
import tempfile
from pathlib import Path
import publish_u3_coverage as publication
import integrate_u3_predecessors as gates
from broker import u3_delivery_review as review
from release_eval import save_receipt

RECEIPT=publication.ROOT/'.local-port2/release-receipts/U3-COVERAGE-INTEGRATION.json'


def load_final():
    script='''import broker as b,u3_delivery_review as r,json
with b.LOCK:
 c,s=r.saved(b)
 if s['stage']!='delivery_review_approved' or s['delivery_approval'] is not True:raise ValueError('actual final approval required')
 parent,settings,fx=r.current(b,c)
 tasks=r.tasks_for_wake(settings,c,s)
 if len(tasks)!=1:raise ValueError('one final native review required')
 t=tasks[0]
 if b.review_decisions(r.native.task_messages(settings,t['id']))!=['APPROVE']:raise ValueError('exact native APPROVE required')
 with b.db() as con:
  decision=con.execute('SELECT * FROM reviews WHERE review_task_id=?',(t['id'],)).fetchone()
  rpc=con.execute('SELECT s.status,s.receipt FROM review_suite_rpc s JOIN native_bindings n USING(request_id) WHERE n.task_id=?',(t['id'],)).fetchall()
 if not decision or len(rpc)!=1 or rpc[0]['status']!='passed':raise ValueError('exact actual review and RPC required')
 actual=r.receipt(c,s,t,dict(decision),json.loads(rpc[0]['receipt']),fx.read_evidence(t),parent['intake']['seed']['task_id'])
 if actual!=s['receipt']:raise ValueError('final independent receipt drift')
 print(json.dumps(actual))
'''
    return json.loads(publication.run('docker','exec','-e','PYTHONPATH=/',
        publication.PROJECT+'-execution-broker-1','python','-c',script))


def qualify(published,bundle,final):
    publication.validate_bundle(bundle)
    if (published.get('stage')!='pr_open' or published.get('pr_number')!=36
            or published.get('head_sha')!=review.HEAD or published.get('base_sha')!=review.BASE
            or published.get('manifest_sha256')!=bundle['contract']['manifest_sha256']
            or published.get('review_receipt_sha256')!=publication.digest(bundle['receipt'])
            or final.get('schema')!='u3-final-coverage-review-v1'
            or final.get('head_sha')!=review.HEAD or final.get('base_sha')!=review.BASE
            or final.get('pr_url')!=review.PR or final.get('source_task')!=bundle['source_task']
            or final.get('reviewer')!=review.REVIEWER or final['reviewer']==bundle['contract']['author']
            or final.get('manifest_sha256')!=published['manifest_sha256']
            or final.get('delivery_approval') is not True
            or any(final.get(k) is not False for k in ('historical_tdd_red','product_admission_authorized',
                                                      'merge_authorized','deploy_authorized'))
            or any(not re.fullmatch('[a-f0-9]{64}',final.get(k,'')) for k in ('suite_sha256','reads_sha256'))):
        raise ValueError('exact final independently reviewed coverage required')


def verify_pr(pr,published):
    if (pr.get('number')!=36 or pr.get('head',{}).get('sha')!=published['head_sha']
            or pr.get('head',{}).get('ref')!=publication.BRANCH
            or pr.get('base',{}).get('ref')!='main'
            or pr.get('base',{}).get('sha') not in ({published['base_sha'],pr.get('merge_commit_sha')}
                if pr.get('merged') else {published['base_sha']})
            or any(pr.get(side,{}).get('repo',{}).get('full_name')!=publication.REPOSITORY
                   for side in ('head','base'))):
        raise ValueError('exact same-repository coverage PR required')


def intent(published,final,protection,head_ci):
    return dict(schema='u3-coverage-integration-v1',stage='merge_intent',
        repository=publication.REPOSITORY,pr_number=36,base_sha=review.BASE,head_sha=review.HEAD,
        publication_sha256=publication.digest(published),final_review_sha256=publication.digest(final),
        final_review=final,manifest_sha256=final['manifest_sha256'],head_ci=head_ci,
        protection_sha256=publication.digest(protection),historical_tdd_red=False,
        product_admission_authorized=False,deploy_authorized=False)


def verify_intent(saved,published,final,protection):
    if (saved.get('schema')!='u3-coverage-integration-v1' or saved.get('repository')!=publication.REPOSITORY
            or saved.get('pr_number')!=36 or saved.get('base_sha')!=review.BASE or saved.get('head_sha')!=review.HEAD
            or saved.get('publication_sha256')!=publication.digest(published)
            or saved.get('final_review_sha256')!=publication.digest(final) or saved.get('final_review')!=final
            or saved.get('protection_sha256')!=publication.digest(protection)
            or saved.get('manifest_sha256')!=final['manifest_sha256']):
        raise ValueError('durable exact merge intent required')


def may_dispatch(saved):
    return saved is None or saved.get('stage')=='merge_intent'


def main(*,merge=False):
    for path in (publication.RECEIPT,RECEIPT):
        if path.is_symlink():raise ValueError('regular integration receipts required')
    published=json.loads(publication.RECEIPT.read_text())
    bundle=publication.load_bundle();final=load_final();qualify(published,bundle,final)
    protection=gates.api('branches/main/protection');gates.protection_ok(protection)
    pr=gates.api('pulls/36');verify_pr(pr,published)
    head_ci=gates.exact_ci(gates.api('commits/'+review.HEAD+'/check-runs'),review.HEAD)
    with tempfile.TemporaryDirectory(prefix='u3-coverage-merge-') as tmp:
        snapshot=Path(tmp);publication.export_snapshot(bundle,snapshot)
        content=publication.preflight(publication.REPO,bundle,snapshot,target_base=review.BASE)
        publication.verify_commit(publication.REPO,review.HEAD,review.BASE,content)
    saved=json.loads(RECEIPT.read_text()) if RECEIPT.is_file() else None
    if saved:verify_intent(saved,published,final,protection)
    if not pr.get('merged'):
        if pr.get('state')!='open' or publication.remote_base(publication.REPO)!=review.BASE:
            raise ValueError('open PR on exact reviewed main required')
        if not may_dispatch(saved):
            print(json.dumps(dict(stage='merge_observation_pending',owner='cto',
                next_action='Observe previous remote merge attempt; never repeat an uncertain PUT')));return
        base,binding=publication.publication_base(bundle)
        if base!=review.BASE or binding!=published['git_binding']:raise ValueError('predecessor Git binding drift')
        if not merge:
            print(json.dumps(dict(stage='merge_preconditions_passed',head_sha=review.HEAD,
                final_review_sha256=publication.digest(final))));return
        saved=intent(published,final,protection,head_ci);save_receipt(RECEIPT,saved)
        if load_final()!=final or publication.load_bundle()!=bundle or gates.api('branches/main/protection')!=protection:
            raise ValueError('review or branch protection drift before merge')
        verify_pr(gates.api('pulls/36'),published)
        gates.exact_ci(gates.api('commits/'+review.HEAD+'/check-runs'),review.HEAD)
        if publication.remote_base(publication.REPO)!=review.BASE:raise ValueError('main moved before merge')
        saved['stage']='merge_dispatched';save_receipt(RECEIPT,saved)
        try:
            result=gates.api('pulls/36/merge','--method','PUT','-f','sha='+review.HEAD,'-f','merge_method=squash')
            if result.get('merged') is not True:raise ValueError('protected merge not accepted')
        except Exception:
            saved.update(stage='merge_observation_pending',owner='cto')
            save_receipt(RECEIPT,saved)
            raise
        pr=gates.api('pulls/36');verify_pr(pr,published)
    if saved is None:raise ValueError('durable intent required for observed merge')
    merged=pr.get('merge_commit_sha')
    if not pr.get('merged') or not merged or publication.remote_base(publication.REPO)!=merged:
        raise ValueError('exact observed coverage merge required')
    if gates.api('branches/main/protection')!=protection:raise ValueError('branch protection changed')
    publication.git(publication.REPO,'fetch','origin',merged)
    tree=gates.verify_merged(publication.REPO,review.BASE,review.HEAD,merged)
    saved.update(stage='waiting_main_ci',merged_sha=merged,tree_sha=tree,protection_preserved=True)
    save_receipt(RECEIPT,saved)
    try:main_ci=gates.exact_ci(gates.api('commits/'+merged+'/check-runs'),merged)
    except gates.CIWaiting:
        print(json.dumps(saved));return
    except ValueError:
        saved.update(stage='blocked_main_ci',owner='cto',next_action='Diagnose exact merged-SHA CI; do not deploy')
        save_receipt(RECEIPT,saved);print(json.dumps(saved));return
    saved.update(stage='coverage_integrated',main_ci=main_ci)
    save_receipt(RECEIPT,saved);print(json.dumps(saved))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--merge',action='store_true')
    main(merge=parser.parse_args().merge)
