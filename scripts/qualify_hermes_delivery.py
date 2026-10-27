"""Native dispatch + real AIAgent delivery tools + Docker TDD; scripted model.

Only the initial graph is supplied by the fixture. Claims, review/change handoffs,
test freeze, dependency release and completion use native lifecycle operations.
No external model, real GitHub, deployment or autonomous-product claim.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_s1 import prepare
from qualify_hermes_agent import check_dependencies
from fabriquinha.artifacts import Store
from fabriquinha.board import Board
from fabriquinha.config import Project
from fabriquinha.effects import write_json,Pending,EffectBlocked
from fabriquinha.executor import Runner, docker
from fabriquinha.hermes import Sandbox, run_activity
from fabriquinha.kanban_lane import native
from fabriquinha.quality import Quality
from fabriquinha.publication import Repository,LocalCI


def steps(run,changes,*,known_regression=False):
    if known_regression:
        if run.reviewing:
            return [('read_file',{'path':'/workspace/tests/test_existing.py'}),('delivery_review',dict(
                decision='approve',reason='Existing behavior expectation and exact regression failures independently confirmed.',findings=[]))]
        if run.kind=='tests':return [('read_file',{'path':'/workspace/tests/test_existing.py'}),('delivery_submit',{})]
    test='/workspace/tests/test_new.py'
    if run.reviewing:
        decision=dict(decision='approve',reason='Independent fixture review of actual recorded evidence',findings=[])
        if run.kind=='tests' and not changes:
            decision=dict(decision='changes',reason='The approved behavior requires value 2, not 3',
                findings=[dict(path='tests/test_new.py',line=3,detail='Expect value 2')])
        return [('read_file',{'path':test}),('delivery_review',decision)]
    if run.kind=='tests':
        if changes:return [('read_file',{'path':test}),('patch',dict(path=test,old_string='app.VALUE,3',new_string='app.VALUE,2')),
                           ('delivery_submit',{})]
        return [('delivery_submit',{}),('read_file',{'path':'/workspace/app.py'}),
            ('write_file',dict(path=test,content='import unittest, app\nclass NewBehavior(unittest.TestCase):\n def test_value(self): self.assertEqual(app.VALUE,3)\n')),
            ('delivery_submit',{})]
    return [('read_file',{'path':'/workspace/app.py'}),('write_file',dict(path='/workspace/app.py',content='VALUE = 2\n')),
            ('delivery_submit',{'mutations':[{'app.py':'VALUE = 1\n'}]})]


def worker(root,upstream,task,number):
    home=prepare(root,upstream);kb,kbc,dispatch=native()
    with kbc.connect_closing() as conn:
        if not dispatch.adopt_worker_pid(conn,task,number,os.getpid()):raise ValueError('claim lost before worker startup')
        changes=conn.execute('SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind=?',(task,'changes_requested')).fetchone()[0]
        prompt=kb.build_worker_context(conn,task)
    project=Project.parse(json.loads((root/'project.json').read_bytes()));store=Store(root/'private');board=Board(project)
    run=board.current(task,number)
    os.environ.update(HERMES_HOME=str(home/'profiles'/run.actor),HERMES_DISABLE_LAZY_INSTALLS='1')
    quality=Quality(project,store,Runner(project,store),board)
    if run.kind=='implementation' and not run.reviewing:
        workspace=board.workspace(run)
        frozen=quality.freeze(run,board.input(run,'tests'))
        if not any(workspace.iterdir()):store.checkout(frozen['snapshot'],workspace)
        else:quality.protect(frozen['snapshot'],store.capture(workspace),exact_tests=True)
    known_regression=(root/'regression-base.json').exists()
    sandbox=Sandbox(project,store,board,run);sequence=steps(run,changes,known_regression=known_regression);requests=[]
    class Response(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            index=len(requests);requests.append(body)
            if not re.fullmatch(r'(?:/activities/[a-f0-9]{64})?/v1/chat/completions',self.path) or body.get('stream') or index>=len(sequence):
                self.send_error(400);return
            name,args=sequence[index]
            message=dict(role='assistant',content=None,tool_calls=[dict(id='flow-'+str(number)+'-'+str(index),
                type='function',function=dict(name=name,arguments=json.dumps(args)))])
            value=dict(id='local-'+str(index),object='chat.completion',created=int(time.time()),model=body['model'],
                choices=[dict(index=0,message=message,finish_reason='tool_calls')],
                usage=dict(prompt_tokens=100,completion_tokens=50,total_tokens=150))
            data=json.dumps(value).encode();self.send_response(200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Response)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=run_activity(sandbox,quality,dict(base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',
            api_key='offline-fixture',provider='custom',api_mode='chat_completions',model='fabriquinha-native-flow-fixture'),prompt)
        assert len(requests)==len(sequence),(len(requests),len(sequence))
        from hermes_state import SessionDB
        with SessionDB() as db:
            messages=db.get_messages(result['session'])
        terminal_tool='delivery_review' if run.reviewing else 'delivery_submit'
        persisted=[json.loads(m['content']) for m in messages if m.get('tool_name')==terminal_tool]
        assert persisted and persisted[-1]==result['transition'],'terminal tool result must survive session persistence'
        if run.kind=='tests' and not run.reviewing and not changes and not known_regression:
            tool_messages=[m for m in requests[1]['messages'] if m.get('role')=='tool']
            assert tool_messages and 'Red must fail new behavior' in str(tool_messages[-1])
        write_json(root/'runs'/str(number)/'activity.json',dict(binding=run.binding(),local_requests=len(requests),
            synthetic_responses=True,model_calls=0,result=result))
    except Exception as error:
        with kbc.connect_closing() as conn:
            current=kb.get_task(conn,task)
            if current.status=='running' and current.current_run_id==number:
                kb.block_task(conn,task,reason='Native delivery fixture worker failed: '+type(error).__name__,expected_run_id=number)
        raise
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);sandbox.close()


def create_trial(root,upstream,image,*,namespace='delivery-kit-hermes-native-flow',known_regression=False):
    if root.exists():raise ValueError('fresh private root required')
    root.mkdir(mode=0o700,parents=True);check_dependencies();home=prepare(root,upstream)
    os.environ['HERMES_DISABLE_LAZY_INSTALLS']='1';kb,kbc,dispatch=native()
    with kbc.connect_closing():pass
    from hermes_cli.profiles import create_profile
    for name in ('flow-author','flow-reviewer'):
        create_profile(name,no_skills=True,description='Scripted native TDD handoff qualification')
        write_json(home/'profiles'/name/'config.yaml',dict(model={'streaming':False,'context_length':65536},
            auxiliary={'title_generation':{'enabled':False}},
            tools={'tool_search':{'enabled':'off'}},terminal={'backend':'fabriquinha','cwd':'/workspace'}))
    project=dict(version=1,namespace=namespace,repository='https://github.com/example/qualification',
        branch='release/qualification',validation_image=image,tests_dir='tests',reviewers={'flow-author':'flow-reviewer'},qualification=True)
    write_json(root/'project.json',project);store=Store(root/'private')
    source=root/'work/tests';(source/'tests').mkdir(parents=True)
    (source/'app.py').write_text('VALUE = 1\n')
    (source/'tests/test_existing.py').write_text('import unittest, app\nclass Existing(unittest.TestCase):\n def test_type(self): self.assertIsInstance(app.VALUE,int)\n')
    if known_regression:
        with (source/'tests/test_existing.py').open('a') as stream:
            stream.write(' def test_value(self): self.assertEqual(app.VALUE,2)\n def test_offsets(self):\n  for offset in (0,1):\n   with self.subTest(offset=offset):self.assertEqual(app.VALUE+offset,2+offset)\n')
        remote=root/'remote.git';remote.mkdir();fixture_git(remote,'init','--bare','--initial-branch=main')
        fixture_git(source,'init','--initial-branch=main');fixture_git(source,'add','.')
        fixture_git(source,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','Existing failing behavior fixture')
        fixture_git(source,'remote','add','origin',str(remote));fixture_git(source,'push','origin','HEAD:refs/heads/'+project['branch'])
        write_json(root/'regression-base.json',dict(commit=fixture_git(source,'rev-parse','HEAD')))
    for path in [source,*source.rglob('*')]:path.chmod(0o777 if path.is_dir() else 0o666)
    baseline=store.capture(source);implementation=root/'work/implementation';implementation.mkdir(mode=0o777)
    implementation.chmod(0o777)
    with kbc.connect_closing() as conn:
        tests=kb.create_task(conn,title='Native fixture tests, Red and independent freeze',
            body=json.dumps(dict(version=1,kind='tests',release='native-flow',inputs={
                'baseline':baseline,**({'base_commit':json.loads((root/'regression-base.json').read_bytes())['commit']} if known_regression else {})},criteria='VALUE must become 2')),
            assignee='flow-author',workspace_kind='dir',workspace_path=str(source),completion_contract='local-only',max_retries=2,max_runtime_seconds=600)
        impl=kb.create_task(conn,title='Native fixture implementation with protected tests',
            body=json.dumps(dict(version=1,kind='implementation',release='native-flow',inputs={'tests':'parent:'+tests+':tests'})),
            assignee='flow-author',workspace_kind='dir',workspace_path=str(implementation),parents=[tests],
            completion_contract='local-only',max_retries=2,max_runtime_seconds=600)
    return tests,impl


def fixture_git(folder,*args):
    return subprocess.run(['git','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false','-C',str(folder),*args],
        check=True,capture_output=True,text=True).stdout.strip()


def regression_ci(root,project,store,board,impl):
    """Real local Git/Docker boundaries; scripted decisions are not model judgment."""
    run,metadata,_=board.closed_review(impl)
    review=store.receipt(metadata['delivery'],kind='delivery_review');green=store.receipt(review['payload']['green'],kind='green')
    quality=Quality(project,store,Runner(project,store),board);frozen=quality.frozen_plan(store.receipt(green['payload']['freeze'],kind='tests_frozen'))
    red=quality.test_evidence(frozen['red']);assert red['kind']=='regression_red' and frozen['new_cases']==[]
    failures=store.receipt(red['payload']['red_job'],kind='suite_job')['payload']['report']['failures']
    assert len(failures)>len({failure['case'] for failure in failures}),'real subtest failures must remain individually recorded'
    repo=Repository(project,store,remote=root/'remote.git');base=repo.base();assert red['payload']['base_commit']==base
    ci=LocalCI(project,store,repo,quality.runner)
    def wait(call):
        until=time.monotonic()+project.timeout_seconds*3+45
        while True:
            try:return call()
            except Pending:
                if time.monotonic()>until:raise
                time.sleep(.1)
    snapshot=green['payload']['snapshot'];head=repo.propose(snapshot,base,'fixture/repair',run.actor);repo.push('fixture/repair',head)
    proposal=wait(lambda:ci.validate(head,base,stage='proposal'));facts=store.receipt(proposal)['payload']
    assert facts['conclusion']=='success' and facts['regression_review']==metadata['delivery']
    changed=root/'unreviewed';store.checkout(snapshot,changed);(changed/'app.py').write_text('VALUE = 3\n')
    stale=repo.propose(store.capture(changed),base,'fixture/stale-review',run.actor);repo.push('fixture/stale-review',stale)
    try:wait(lambda:ci.validate(stale,base,stage='proposal'))
    except EffectBlocked:pass
    else:raise AssertionError('another snapshot reused the regression review')
    repo.push(project.branch,head)
    integrated=wait(lambda:ci.validate(head,base,stage='integrated'))
    assert store.receipt(integrated)['payload']['conclusion']=='success'
    # A distinct Git commit with identical defective files is still another SHA.
    other=repo.propose(red['payload']['baseline'],head,'fixture/same-tree',run.actor);repo.push(project.branch,other)
    rebased=repo.propose(snapshot,other,'fixture/rebased',run.actor);repo.push('fixture/rebased',rebased)
    try:wait(lambda:ci.validate(rebased,other,stage='proposal'))
    except EffectBlocked:pass
    else:raise AssertionError('another base SHA reused the regression review')
    # Only local fixture refs advanced, without force or history rewriting.
    assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project.namespace+'-tests').strip()
    return dict(proposal=proposal,integrated=integrated,base_commit=base,head=head,
        existing_tests_unchanged=quality.tests(snapshot)==quality.tests(red['payload']['baseline']),
        stale_snapshot_rejected=True,other_base_sha_rejected=True,real_local_git=True,github=False)


def qualify(root,upstream,image,*,known_regression=False):
    tests,impl=create_trial(root,upstream,image,known_regression=known_regression,
        namespace='delivery-kit-hermes-native-regression' if known_regression else 'delivery-kit-hermes-native-flow')
    kb,kbc,dispatch=native()
    project=json.loads((root/'project.json').read_bytes())
    source=root/'work/tests';implementation=root/'work/implementation'
    children=[]
    def spawn(task,workspace,*,board=None):
        folder=root/'runs'/str(task.current_run_id);folder.mkdir(parents=True,mode=0o700)
        with (folder/'worker.log').open('wb') as log:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--root',str(root),'--upstream',str(upstream),
                '--worker','--task',task.id,'--run',str(task.current_run_id)],stdout=log,stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},start_new_session=True)
        children.append(proc);return proc.pid
    deadline=time.monotonic()+300
    while True:
        for child in children:child.poll()
        with kbc.connect_closing() as conn:
            dispatch.dispatch_once(conn,spawn_fn=spawn,max_spawn=2,max_in_progress=2,max_in_progress_per_profile=1)
            cards=[kb.get_task(conn,ident) for ident in (tests,impl)]
        if any(card.status=='blocked' for card in cards):raise RuntimeError('native fixture card blocked; inspect private worker log')
        if all(card.status=='done' for card in cards) and all(child.poll() is not None for child in children):break
        if time.monotonic()>=deadline:raise TimeoutError('native fixture observation deadline exceeded; do not restart live workers')
        time.sleep(0.25)
    with kbc.connect_closing() as conn:
        runs=[dict(row) for row in conn.execute('SELECT id,task_id,profile,outcome FROM task_runs ORDER BY id')]
        expected=(['review_requested','completed','review_requested','completed'] if known_regression else
            ['review_requested','changes_requested','review_requested','completed','review_requested','completed'])
        assert [r['outcome'] for r in runs]==expected,runs
        assert conn.execute('SELECT COUNT(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]==0
    assert all(child.returncode==0 for child in children),'a worker failed after its native handoff'
    activities=[json.loads((root/'runs'/str(row['id'])/'activity.json').read_bytes()) for row in runs]
    if not known_regression:assert activities[2]['result']['resumed'] and activities[3]['result']['resumed']
    assert (source/'app.py').read_text()=='VALUE = 1\n' and (implementation/'app.py').read_text()=='VALUE = 2\n'
    assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project['namespace']+'-tests').strip()
    extra=regression_ci(root,Project.parse(project),Store(root/'private'),Board(Project.parse(project)),impl) if known_regression else {}
    result=dict(native_dispatch=True,native_agent=True,native_delivery_tools=True,real_docker_tdd=True,known_regression=known_regression,
        changes_returned_and_corrected=not known_regression,frozen_tests_preserved=True,negative_control_verified=True,
        independent_delivery_review=True,native_completed_cards=2,activities=len(runs),
        resumed_author_and_reviewer_sessions=not known_regression,local_http_requests=sum(a['local_requests'] for a in activities),
        synthetic_responses=True,model_calls=0,delivery_approval=False,migration=False,regression_ci=extra)
    write_json(root/'receipt.json',result);print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image');parser.add_argument('--worker',action='store_true')
    parser.add_argument('--task');parser.add_argument('--run',type=int);parser.add_argument('--known-regression',action='store_true');args=parser.parse_args()
    if args.worker:worker(args.root.resolve(),args.upstream.resolve(),args.task,args.run)
    else:
        root=args.root.resolve();fresh=not root.exists()
        try:qualify(root,args.upstream.resolve(),args.image,known_regression=args.known_regression)
        except Exception as error:
            # An observation deadline is not permission to retire a live worker.
            # Each worker owns its cleanup; preserve native state for diagnosis.
            if fresh and root.exists():write_json(root/'failure.json',dict(qualification=False,model_calls=0,
                error=type(error).__name__,reason=str(error),native_state_preserved=True))
            raise
