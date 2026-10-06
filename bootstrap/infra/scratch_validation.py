"""Exact registered contracts for isolated validation cards, not LLM verdicts."""
import hashlib
import json
from pathlib import Path
import re


def verify_registered(conn,task_id,row,require_review=True):
    database=conn.execute('PRAGMA database_list').fetchone()[2]
    if not database:
        return
    contracts=Path(database).parent/'validation-contracts.json'
    if not contracts.exists():
        return
    contract=json.loads(contracts.read_text()).get(task_id)
    if not contract:
        return
    root=Path(row['workspace_path']).resolve(strict=True)
    report=json.loads((root/'validation-result.json').read_text())
    if report.get('task')!=task_id or report.get('stage')!='scratch-validation':
        raise ValueError('validation-result.json must identify this task and scratch-validation stage')
    if report.get('deployment_performed') is not False:
        raise ValueError('this scratch test did not perform deployment')
    sha=hashlib.sha256((root/'test_score.py').read_bytes()).hexdigest()
    if sha!=contract['regression_sha256'] or report.get('regression_sha256')!=sha:
        raise ValueError('preexisting regression changed or its reported hash is incorrect')
    red=(root/'red.log').read_text()
    green=(root/'green.log').read_text()
    def count(text):
        matches=re.findall(r'^Ran (\d+) tests? in ',text,re.M)
        if len(matches)!=1:
            raise ValueError('one complete unittest invocation required per evidence log')
        return int(matches[0])
    failures=re.findall(r'^FAILED \(failures=(\d+)\)',red,re.M)
    if len(failures)!=1 or int(failures[0])<1 or '\nOK' not in green or 'FAILED (' in green:
        raise ValueError('actual failed Red and successful Green logs required')
    tests=count(green)
    if count(red)!=tests or tests<contract['minimum_tests']:
        raise ValueError('Red/Green must execute the same complete test suite')
    if type(report.get('tests_run')) is not int or report['tests_run']!=tests:
        raise ValueError(f'report tests_run differs from actual log: expected {tests}')
    if report.get('red_failures')!=int(failures[0]):
        raise ValueError('report red_failures differs from actual Red log')
    if contract.get('runner_required'):
        for stage in ['red','green']:
            receipt=json.loads((root/('runner-'+stage+'.json')).read_text())
            if receipt.get('stage')!=stage or receipt.get('accepted') is not True:
                raise ValueError('accepted runner receipt required: '+stage)
            if hashlib.sha256((root/(stage+'.log')).read_bytes()).hexdigest()!=receipt['log_sha256']:
                raise ValueError('runner log changed: '+stage)
            for name,expected in receipt['tests_sha256'].items():
                if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
                    raise ValueError('tests changed after runner stage '+stage)
        if hashlib.sha256((root/'score.py').read_bytes()).hexdigest()!=receipt['score_sha256']:
            raise ValueError('implementation changed after Green')
    if contract.get('parent'):
        parent=conn.execute('SELECT status,workspace_path FROM tasks WHERE id=?',(contract['parent'],)).fetchone()
        if not parent or parent['status']!='done':
            raise ValueError('QA requires completed parent')
        for name in ['score.py','test_score.py','test_new_score.py','red.log','green.log']:
            if (root/name).read_bytes()!=(Path(parent['workspace_path'])/name).read_bytes():
                raise ValueError('QA must validate the exact parent artifact: '+name)
        qa=(root/'qa.log').read_text()
        if count(qa)!=tests or '\nOK' not in qa or 'FAILED (' in qa:
            raise ValueError('QA requires a successful independent full-suite log')
    if not require_review:
        return
    from review_policy import validate_review
    event=conn.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='review_requested' ORDER BY id DESC LIMIT 1",(task_id,)).fetchone()
    handoff=json.loads(event['payload']) if event else {}
    if handoff.get('implementer')!=contract['implementer'] or validate_review(handoff.get('implementer'),handoff.get('reviewer')):
        raise ValueError('independent canonical review is required')
