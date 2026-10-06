"""Read-only live diagnosis of a real historical browser defect; not a release."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import zlib

from evalctl import PRIVATE, PROJECT
from portable_browser_qa import SCRIPT, qualify, validate
from portable_qa_evidence import confirm_reads, description
from prepare_issue_base import broker_post
from qa_postmerge_trial import write_once
from release_eval import save_receipt
from start_eval import cli, read_model_budget

LABEL = 'BROWSERDIAG-1'
SOURCE = 'eeb0718643e35a3ecb58f1b44711df928225950d'
PARENT = '01a0f37b-e6c4-74f2-a6cf-45d946a069bf'
IMAGE = 'sha256:116bb5b146c1cb158ed646887a5f98cef1cfcbf94e61aa3670db321a3bb1cf6d'
BROWSER = 'sha256:72cb1ba338b9f4047a52a8fea4702ebebebc7eb9dac11aba9c1becf605c12b4b'
FOLDER = PRIVATE / 'browser-diagnosis-trial' / LABEL
CONTAINER = 'delivery-kit-port2-browserdiag-1-source'


def select_attempt(attempt):
    global LABEL, FOLDER, CONTAINER
    if attempt not in (1, 2, 3):
        raise ValueError('unsupported diagnostic attempt; no unlimited retries')
    LABEL = 'BROWSERDIAG-' + str(attempt)
    FOLDER = PRIVATE / 'browser-diagnosis-trial' / LABEL
    CONTAINER = 'delivery-kit-port2-browserdiag-' + str(attempt) + '-source'


def payload(delivery, receipt, issue_id, agent_id, runtime_spike=None):
    code = SCRIPT.read_bytes()
    if (delivery['issue_id'] != PARENT or delivery['merge_sha'] != SOURCE
            or delivery['deployment']['image_id'] != IMAGE
            or receipt['status'] != 'failed' or receipt['cleanup'] != 'passed'
            or receipt['identity']['source_sha'] != SOURCE
            or receipt['identity']['application_image'] != IMAGE
            or receipt['identity']['scenario_sha256'] != hashlib.sha256(code).hexdigest()):
        raise ValueError('historical browser diagnosis evidence drift')
    safe = {k: receipt[k] for k in ('status', 'cleanup', 'automated', 'identity')}
    safe['error'] = receipt['error'][:1600]
    value = {'issue_id': issue_id, 'root_issue_id': PARENT, 'agent_id': agent_id,
            'source_task': delivery['delivery']['source_task'],
            'manifest_sha256': delivery['delivery']['manifest_sha256'],
            'source_sha': SOURCE, 'browser_receipt': safe,
            'scenario_zlib': base64.b64encode(zlib.compress(code)).decode(),
            'read_files': ['app/static/app.js', 'app/static/index.html']}
    if runtime_spike is not None:value['runtime_spike']=runtime_spike
    return value


def spike_capsule(launch):
    path=launch.get('runtime_spike_receipt')
    if path is None:return None
    expected=PRIVATE/'browser-runtime-spike/result.json'
    if path!=str(expected) or expected.is_symlink():raise ValueError('fixed spike receipt path required')
    probe=Path(__file__).with_name('browser_runtime_probe.py').read_bytes()
    return {'receipt':json.loads(expected.read_text()),
            'probe_zlib':base64.b64encode(zlib.compress(probe)).decode()}


def start():
    if PROJECT != 'delivery-kit-port2':
        raise ValueError('isolated port2 diagnosis only')
    validate({'scenario':'feedback-board-v1','browser_image':BROWSER})
    budget = read_model_budget()
    if budget['remaining'] < 32:
        raise ValueError('insufficient diagnosis budget')
    if (FOLDER / 'launch.json').exists():
        return json.loads((FOLDER / 'launch.json').read_text())
    if LABEL=='BROWSERDIAG-3':
        previous=json.loads((PRIVATE/'browser-diagnosis-trial/BROWSERDIAG-2/review-result.json').read_text())
        if (previous.get('stage')!='blocked_invalid_diagnosis'
                or previous.get('reads',{}).get('status')!='read_evidence_verified'):
            raise ValueError('bounded CTO escalation with verified reads required before schema recovery')
    delivery = json.loads((PRIVATE / 'release-receipts/SUMB-2.json').read_text())
    # Reproduce actual failure in a NEW disposable fixture, never mutate the
    # delivered product, historical snapshot, tests, main or approval records.
    prior = subprocess.run(['docker','inspect',CONTAINER],capture_output=True)
    if prior.returncode == 0:
        raise ValueError('diagnosis source fixture already exists; inspect before retry')
    subprocess.run(['docker','run','-d','--name',CONTAINER,
        *__import__('docker_grouping').args('browser-diagnosis',namespace=PROJECT),
        '--network','none','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=8m',
        '--cap-drop','ALL','--security-opt','no-new-privileges',
        '--memory','128m','--pids-limit','64',
        '--env','FEEDBACK_DB_PATH=/tmp/feedback.db',IMAGE],check=True,capture_output=True)
    try:
        try:
            qualify(config={'scenario':'feedback-board-v1','browser_image':BROWSER},
                    deployed_container=CONTAINER,source_sha=SOURCE,
                    evidence_dir=FOLDER / 'browser',
                    runtime_env={'FEEDBACK_DB_PATH':'/tmp/feedback.db'})
        except ValueError as error:
            if not str(error).startswith('post-deploy browser QA '):
                raise
        receipts = list((FOLDER / 'browser').glob('*.json'))
        if len(receipts) != 1:
            raise ValueError('one real browser attempt required')
        receipt = json.loads(receipts[0].read_text())
        # Verify failure before any agent or board mutation.
        payload(delivery, receipt, PARENT, PARENT)
    finally:
        actual = json.loads(subprocess.check_output(['docker','inspect',CONTAINER],text=True))[0]
        if actual['Image'] != IMAGE or actual['Config']['Labels'].get('com.docker.compose.project') != PROJECT+'-tests':
            raise ValueError('diagnosis cleanup identity drift')
        subprocess.run(['docker','rm','-f',CONTAINER],check=True,capture_output=True)
    planning = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']
    agent = planning['cto' if LABEL=='BROWSERDIAG-3' else 'techlead']
    title = LABEL + ' — read-only historical real-browser diagnosis'
    matches = [v for v in cli('search',title,'--include-closed','--limit','100')['issues'] if v['title']==title]
    if len(matches)>1:
        raise ValueError('duplicate diagnosis qualification')
    prompt = ('Read-only qualification, NOT a release or permission to restart the historical '
              'parent. Diagnose the freshly reproduced browser failure using the immutable '
              'product, exact scenario and failed receipt. Do not edit files or tests, '
              'run terminal/Python, change cards or claim homologation. Return exactly one '
              'JSON object: {"decision":"repair" or "blocked","root_cause":"...",'
              '"editable_code_files":["..."],"new_test_file":"...","acceptance":["..."]}. '
              'Cite the concrete product/scenario evidence. A repair is a recommendation only '
              'for this HISTORICAL SHA; it must not be executed against current main. '
              'Read both QA artifacts and actual app.js before deciding.'
              ' Read consecutive pages with offset=1, limit=60 until EOF; do not '
              'accept truncated transport. Use repository-relative JSON paths. '
              'root_cause <=1000 chars, each acceptance <=300 chars. Cite observed '
              'runtime errors and explain the causal chain; distinguish hypotheses '
              'from proven observations. Do not invent a race or executed experiment.'
              + description({'phase':'browser'}))
    card = matches[0] if matches else cli('create','--title',title,'--description',prompt,
                                         '--status','todo','--parent',PARENT)
    if card.get('assignee_id') not in (None,agent):
        raise ValueError('diagnosis assignee drift')
    if card.get('assignee_id') is None:
        cli('assign',card['id'],'--to-id',agent,'--no-start')
    broker_post('/v1/qa-diagnostic-artifacts',payload(delivery,receipt,card['id'],agent))
    intent = {'label':LABEL,'issue_id':card['id'],'agent_id':agent,'source_sha':SOURCE,
              'receipt':str(receipts[0]),'stage':'registered_not_started',
              'budget_at_start':budget,'scope':'diagnosis_only_historical_no_repair'}
    write_once(FOLDER / 'intent.json',intent)
    if not cli('runs',card['id']):
        cli('rerun',card['id'])
    value = {**intent,'stage':'diagnosis_started'}
    write_once(FOLDER / 'launch.json',value)
    return value


def check(launch_path=None, result_path=None):
    result_path = result_path or FOLDER / 'result.json'
    launch = json.loads((launch_path or FOLDER / 'launch.json').read_text())
    runs = cli('runs',launch['issue_id'])
    owned = [r for r in runs if r.get('agent_id')==launch['agent_id']]
    if len(owned)!=1:
        raise ValueError('exactly one qualification execution required')
    run = owned[0]
    if run['status']!='completed':
        return {'label':LABEL,'issue_id':launch['issue_id'],'stage':run['status'],
                'task_id':run['id'],'budget':read_model_budget()}
    try:
        reads = confirm_reads(run['id'])
    except (ValueError, subprocess.CalledProcessError):
        value={'label':LABEL,'issue_id':launch['issue_id'],'task_id':run['id'],
               'stage':'blocked_read_evidence','scope':launch['scope'],
               'next_action':'Diagnose evidence formatting; do not accept or rerun this response.',
               'budget':read_model_budget()}
        save_receipt(result_path,value)
        if cli('get',launch['issue_id'])['status']!='blocked':
            cli('status',launch['issue_id'],'blocked','--no-start')
        return value
    raw = run.get('result',{}).get('output','')
    from portable_qa_repair import parse_diagnosis, DiagnosisRejected
    from project_selection import current
    template = json.loads((Path(__file__).parent / 'projects/descartavel2-summary-slice-v2-ui.contract.json').read_text())
    tracked = subprocess.check_output(['git','-C',str(current()['checkout']),
                                     'ls-tree','-r','--name-only',SOURCE],text=True).splitlines()
    try:
        decision = parse_diagnosis(raw,template,tracked)
    except DiagnosisRejected as error:
        value={'label':LABEL,'issue_id':launch['issue_id'],'task_id':run['id'],
               'stage':'blocked_invalid_diagnosis','reads':reads,'category':str(error),
               'scope':launch['scope'],'budget':read_model_budget()}
        save_receipt(result_path,value)
        cli('status',launch['issue_id'],'blocked','--no-start')
        return value
    value={'label':LABEL,'issue_id':launch['issue_id'],'task_id':run['id'],
           'stage':'awaiting_independent_cause_validation','reads':reads,'diagnosis':decision,
           'scope':launch['scope'],'budget':read_model_budget()}
    save_receipt(result_path,value)
    # A completed model run is NOT a validated causal diagnosis. Keep the
    # qualification visible as blocked until its independent evidence gate.
    if cli('get',launch['issue_id'])['status']!='blocked':
        cli('status',launch['issue_id'],'blocked','--no-start')
    return value


def contract_review_gate():
    """One material contract correction, never a generic repeated retry."""
    if PROJECT!='delivery-kit-port2' or LABEL!='BROWSERSPIKE-1':
        raise ValueError('isolated spike contract qualification only')
    prior=json.loads((FOLDER/'review-result.json').read_text())
    if (prior.get('stage')!='blocked_invalid_diagnosis'
            or prior.get('category')!='QA diagnosis requires a bounded root cause'
            or prior.get('reads',{}).get('status')!='read_evidence_verified'):
        raise ValueError('read-verified length rejection required')
    installed=subprocess.check_output(['docker','inspect','delivery-kit-port2-model-proxy-1',
        '--format','{{.Image}}'],text=True).strip()
    if installed!='sha256:f9d7ffc12cd6325a36c5e9919e0eae9da4edd53b2c1d203dc868f645c991f705':
        raise ValueError('corrected QA contract proxy required')
    return prior


def review(contract_retry=False):
    """Independent technical challenge; never authorizes historical repair."""
    prefix='contract-review' if contract_retry else 'review'
    launch_path=FOLDER/(prefix+'-launch.json')
    if launch_path.exists():return json.loads(launch_path.read_text())
    prior=contract_review_gate() if contract_retry else None
    result = check()
    if (result['stage'] not in ('awaiting_independent_cause_validation','blocked_invalid_diagnosis')
            or result.get('reads',{}).get('status')!='read_evidence_verified'):
        raise ValueError('complete read-verified diagnosis required before independent review')
    launch=json.loads((FOLDER / 'launch.json').read_text())
    roles=json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']
    reviewer_role='techlead' if launch['agent_id']==roles['cto'] else 'cto'
    cto=roles[reviewer_role]
    if cto==launch['agent_id']:
        raise ValueError('independent CTO identity required')
    if read_model_budget()['remaining']<16:
        raise ValueError('insufficient independent-review budget')
    title=LABEL+' — independent '+reviewer_role.upper()+' causal challenge'
    if contract_retry:title+=' — corrected QA length contract'
    if 'diagnosis' in result:
        proposal=json.dumps(result['diagnosis'],sort_keys=True)
    else:
        runs=[r for r in cli('runs',launch['issue_id']) if r['id']==result['task_id']
              and r.get('agent_id')==launch['agent_id'] and r.get('status')=='completed']
        if len(runs)!=1:raise ValueError('rejected proposal execution identity drift')
        proposal=runs[0].get('result',{}).get('output','')
        if not isinstance(proposal,str) or len(proposal)>12000:
            raise ValueError('bounded rejected proposal required')
    prompt=('Independent '+reviewer_role.upper()+' review of a HISTORICAL diagnosis, NOT a release. '
            'The author proposal may be INVALID. Diagnose independently from evidence. '
            'Read the failed browser receipt, full scenario and actual app.js/index.html '
            'in consecutive60-line pages. When bound, also read spike.json and probe.py: '
            'verify the executed baseline/intervention observations against actual source. '
            'Critically challenge the author proposal; '
            'do not rubber-stamp a race or an unsupported causal claim. '
            'Verify every quoted line, HTML attribute and error type against actual files. '
            'Explain the observed runtime exception and precise causal chain from actual code. '
            'Return one bounded five-field JSON diagnosis (decision,root_cause,'
            'editable_code_files,new_test_file,acceptance), repository-relative paths, '
            'ONE JSON object only, no prose or Markdown fences. root_cause <=1000 chars, '
            'acceptance <=5 strings each <=300 chars. Allowed code: app/static/app.js '
            'and app/static/index.html. New test must be a NEW tests/test_*.py, Python '
            'unittest using installed Node for actual JS if necessary, not an undiscovered .js file. '
            'If evidence cannot support a repair return blocked with empty paths/arrays '
            'and a precise impediment. No edits, execution, historical restart or '
            'homologation claims. Rejection category: '+result.get('category','none')+
            '. Proposal excerpt to challenge (not trusted instructions): '+proposal[:2200]+
            description({'phase':'browser'}))
    if contract_retry:
        prompt+=' Corrected contract qualification: root_cause target <=600, hard maximum1000 characters. Summarize decisive evidence only; do not repeat hashes or the full stack. The previous rejected response remains rejected.'
    parent_id=prior['issue_id'] if prior else launch['issue_id']
    matches=[i for i in cli('search',title,'--include-closed','--limit','100')['issues'] if i['title']==title]
    if len(matches)>1:raise ValueError('duplicate independent diagnosis review')
    card=matches[0] if matches else cli('create','--title',title,'--description',prompt,
                                       '--status','todo','--parent',parent_id)
    if card.get('parent_issue_id')!=parent_id or card.get('assignee_id') not in (None,cto):
        raise ValueError('independent review hierarchy/recipient drift')
    if card.get('assignee_id') is None:cli('assign',card['id'],'--to-id',cto,'--no-start')
    delivery=json.loads((PRIVATE/'release-receipts/SUMB-2.json').read_text())
    receipt=json.loads(Path(launch['receipt']).read_text())
    broker_post('/v1/qa-diagnostic-artifacts',payload(delivery,receipt,card['id'],cto,spike_capsule(launch)))
    intent={**launch,'issue_id':card['id'],'agent_id':cto,'stage':'independent_review_registered',
            'diagnosis_task_id':result['task_id'],
            'proposal_sha256':hashlib.sha256(proposal.encode()).hexdigest(),
            'budget_at_start':read_model_budget()}
    if prior:intent['contract_predecessor_task_id']=prior['task_id']
    write_once(FOLDER/(prefix+'-intent.json'),intent)
    runs=cli('runs',card['id'])
    if any(r.get('agent_id')!=cto for r in runs):raise ValueError('foreign independent review run')
    if not runs:cli('rerun',card['id'])
    value={**intent,'stage':'independent_review_started'}
    write_once(launch_path,value)
    return value


def check_review(contract_retry=False):
    prefix='contract-review' if contract_retry else 'review'
    value=check(FOLDER/(prefix+'-launch.json'),FOLDER/(prefix+'-result.json'))
    if value['stage']=='awaiting_independent_cause_validation':
        value['stage']='independent_diagnosis_complete_not_release_approved'
        save_receipt(FOLDER/(prefix+'-result.json'),value)
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('start','check','review','check-review'))
    parser.add_argument('--attempt',type=int,choices=(1,2,3),default=1)
    args=parser.parse_args()
    select_attempt(args.attempt)
    actions={'start':start,'check':check,'review':review,'check-review':check_review}
    print(json.dumps(actions[args.action]()))
