"""Compile a fresh narrow C10 correction from the verified current Git tree."""
import json
from pathlib import Path
import subprocess
from audit_search_scope import SHA, run
from generate_dependent_contract import save_generated
from portable_contract import is_test_path, validate
from portable_run_spec import validate as validate_spec

ROOT=Path(__file__).resolve().parent
TEST='tests/test_search_request_generation.py'
LABEL='SEARCHGEN-1'


def derive(tracked, template):
    old=set(tracked)
    if TEST in old:raise ValueError('fresh regression file required')
    if not {'tests/test_incremental_u3.py','app/static/app.js'}<=old:raise ValueError('current reviewed base required')
    files=old|{TEST};editable={TEST,'app/static/app.js'}
    contract=dict(template,files=sorted(files),required_files=sorted(files),
        editable_files=sorted(editable),protected_files=sorted(files-editable),
        test_files=sorted({p for p in old if is_test_path(p,'.','python3')}|{TEST}))
    validate(contract)
    acceptance=('Fix approved C10: a stale board GET must not repaint after a newer GET has rendered, '
        'even when query AND status are identical. Apply a per-page request generation guard. '
        'Preserve query/status race guards, polling, create/complete refresh, summary, drafts, pending '
        'guard, Escape and accessibility. No C11 copy changes or new architecture. '
        'Regression must execute exact app/static/app.js under a faithful DOM/Node harness. '
        'Reuse DRIVER_PREAMBLE from tests/test_incremental_u3.py by importing its literal; '
        'do not duplicate or edit that file, replace app logic or inspect source text as proof. '
        'Issue two same-view GETs, resolve newer then older, verify newest rows remain. '
        'Also cover request-generation race after a query/status round-trip back to the original view. '
        'Do not modify production SOURCE to manufacture Red.')
    spec=dict(label=LABEL,title='C10 — reject stale same-view request generations',
        description=acceptance+' PHASE1 write ONLY '+TEST+' (max32768 bytes). Preserve every '
            'pre-existing test byte-for-byte. Run exactly cd /workspace && PYTHONDONTWRITEBYTECODE=1 '
            'python3 -m unittest discover -s . -q 2>&1. Controller captures genuine Red and sends '
            'frozen tests for independent review before implementation. PHASE2 edit only app/static/app.js '
            'after explicit controller handoff, never approved tests. Use real write tools, not text '
            'simulating actions. No network, GitHub, Docker, credentials or administrative tools. '
            'The old U3 attempt remains historically blocked; this is a fresh regression correction.',
        review_instruction='Review immutable /delivery only. '+acceptance+
            ' Require genuine controller Red, independent frozen test approval, full Green and all '
            'prior tests unchanged. Run only cd /delivery && PYTHONDONTWRITEBYTECODE=1 python3 '
            '-m unittest discover -s . -q 2>&1. No edits, generic terminal/Python or Red recreation. '
            'Finish with Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>. '
            'CI, exact-commit deployment and real-browser generation QA remain mandatory.',
        qa_host_port=19449,container_port=8080,dockerfile='Dockerfile.feedback-bootstrap',
        implementer_registry='pilot-frontend.json',reviewer_registry='pilot-techlead-reviewer.json',
        runtime_env={'FEEDBACK_DB_PATH':'/tmp/feedback.db'},browser_qa=dict(
            browser_image='sha256:72cb1ba338b9f4047a52a8fea4702ebebebc7eb9dac11aba9c1becf605c12b4b',
            scenario='feedback-board-search-generation-v1'))
    validate_spec(spec,contract)
    return contract,spec


def main():
    repo=ROOT/'sandbox-github2'
    observed=run(repo)
    if observed['observed']['stale_same_view_discarded'] is not False:raise ValueError('verified genuine missing behavior required')
    tracked=subprocess.check_output(['git','-C',str(repo),'ls-tree','-r','--name-only',SHA],text=True).splitlines()
    contract,spec=derive(tracked,json.loads((ROOT/'projects/descartavel2-search-1-ui.contract.json').read_text()))
    for suffix,value in [('contract',contract),('run',spec)]:
        save_generated(ROOT/'projects'/('descartavel2-searchgen-1.'+suffix+'.json'),value)
    print(json.dumps(dict(stage='prepared_not_dispatched',base_sha=SHA,label=LABEL,
                         editable_files=contract['editable_files'],protected_tests=len(contract['test_files'])-1)))


if __name__=='__main__':main()
