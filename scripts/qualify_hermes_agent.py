"""Real AIAgent/tools/session DB + real Docker, deterministic loopback responses.

Not model judgement, continuous dispatch, product approval or a release. Run in
a fresh isolated root; each activity is a dedicated worker process.
"""
import argparse
from importlib.metadata import version
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_s1 import prepare
from qualify_hermes_s2 import observe
from fabriquinha.artifacts import Store
from fabriquinha.board import Board
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.executor import Runner, docker
from fabriquinha.hermes import Sandbox, install_backend, restrict_handlers, tool_names
from fabriquinha.kanban_lane import native
from fabriquinha.quality import Quality


def config(image):
    return dict(version=1,namespace='delivery-kit-hermes-agent1',repository='https://github.com/example/qualification',
        branch='release/qualification',validation_image=image,tests_dir='tests',
        reviewers={'tool-author':'tool-reviewer'},qualification=True)


def check_dependencies():
    for line in (ROOT/'scripts/requirements-hermes-agent.txt').read_text().splitlines():
        if line and not line.startswith('#'):
            name,expected=line.split('==')
            if version(name)!=expected:raise ValueError('native-agent dependency pin mismatch: '+name)


def activity(root,upstream,task,number,mode):
    home=prepare(root,upstream)
    project=Project.parse(json.loads((root/'project.json').read_bytes()))
    board=Board(project);run=board.current(task,number)
    os.environ.update(HERMES_HOME=str(home/'profiles'/run.actor),HERMES_DISABLE_LAZY_INSTALLS='1')
    store=Store(root/'private');sandbox=Sandbox(project,store,board,run)
    install_backend(sandbox)
    from run_agent import AIAgent
    from hermes_state import SessionDB
    from tools.registry import registry
    from toolsets import create_custom_toolset
    allowed=tool_names(sandbox)
    create_custom_toolset('fabriquinha_activity','Fixed controller-selected activity',tools=sorted(allowed))
    steps=([('read_file',{'path':'/workspace/app.py'}),
            ('write_file',{'path':'/workspace/app.py','content':'VALUE = 9\n'}),
            ('write_file',{'path':'/workspace/tests/test_new.py','content':
                'import unittest, app\nclass NewBehavior(unittest.TestCase):\n def test_value(self): self.assertEqual(app.VALUE,2)\n'}),
            ('terminal',{'command':'python -m unittest discover -s tests -q','timeout':10})]
           if mode=='author' else [('write_file',{'path':'/workspace/tests/test_new.py','content':'weakened\n'}),
                ('read_file',{'path':'/workspace/tests/test_new.py'})] if mode=='review' else [])
    requests=[]
    class Response(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path!='/v1/chat/completions' or body.get('model')!='fabriquinha-local-fixture' or body.get('stream'):
                self.send_error(400);return
            index=len(requests);requests.append(body)
            if index<len(steps):
                name,args=steps[index]
                message=dict(role='assistant',content=None,tool_calls=[dict(id='native-fixture-'+str(index),
                    type='function',function=dict(name=name,arguments=json.dumps(args)))])
                finish='tool_calls'
            else:message=dict(role='assistant',content='Local fixture activity completed; not a release.');finish='stop'
            value=dict(id='local-'+str(index),object='chat.completion',created=int(time.time()),model=body['model'],
                choices=[dict(index=0,message=message,finish_reason=finish)],
                usage=dict(prompt_tokens=100,completion_tokens=30,total_tokens=130))
            data=json.dumps(value).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Response)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    db=SessionDB();agent=None
    session_path=root/'activity-session.json'
    old=json.loads(session_path.read_bytes()) if mode=='resume' else None
    history=db.get_messages_as_conversation(old['session']) if old else None
    before=db.get_messages(old['session']) if old else []
    try:
        agent=AIAgent(base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',api_key='offline-fixture',
            provider='custom',api_mode='chat_completions',model='fabriquinha-local-fixture',max_iterations=40,
            enabled_toolsets=['fabriquinha_activity'],disabled_toolsets=['kanban'],quiet_mode=True,
            skip_context_files=True,skip_memory=True,skip_background_review=True,session_db=db,
            session_id=old['session'] if old else None,load_soul_identity=False,cwd='/workspace',
            ephemeral_system_prompt='Isolated deterministic infrastructure qualification. No real delivery approval.')
        assert agent.valid_tool_names==allowed,agent.valid_tool_names
        restrict_handlers(sandbox,allowed)
        direct=[]
        if mode=='review':
            for name,args in (('write_file',{'path':'/workspace/app.py','content':'changed'}),
                              ('terminal',{'command':'echo forbidden'}),('kanban_complete',{})):
                result=registry.dispatch(name,args)
                assert 'Unknown tool' in str(result),result
                direct.append(name)
        result=agent.run_conversation('Exercise the assigned '+mode+' activity; this is a deterministic fixture.',
                                      conversation_history=history)
        assert 'Local fixture activity completed' in result['final_response'],result.get('final_response')
        if mode=='author':write_json(session_path,dict(session=agent.session_id))
        session=agent.session_id
        agent.close();agent=None
        after=db.get_messages(session)
        assert after and db.get_session(session)['profile_name']==run.actor
        if mode=='author':
            writes=[json.loads(row['content']) for row in after if row.get('tool_name')=='write_file']
            terminal=[json.loads(row['content']) for row in after if row.get('tool_name')=='terminal']
            assert len(writes)==2 and writes[0].get('error') and 'read-only' in str(writes[0]).lower(),writes
            assert writes[1].get('verified') is True and not writes[1].get('error'),writes[1]
            assert len(terminal)==1 and terminal[0]['exit_code']==1,terminal
        if old:
            assert len(requests)==1 and any(m.get('role')=='tool' for m in requests[0]['messages'])
            assert [m['id'] for m in after[:len(before)]]==[m['id'] for m in before]
            assert len(after)==len(before)+2,(len(before),len(after))
        write_json(root/'activities'/(mode+'.json'),dict(run=run.binding(),local_http_requests=len(requests),
            session=session,db_messages=len(after),session_resumed=bool(old),allowed_tools=sorted(allowed),
            direct_calls_refused=direct,model_calls=0,synthetic_responses=True))
    finally:
        if agent:agent.close()
        db.close();server.shutdown();server.server_close();thread.join(timeout=5)
        sandbox.close()


def qualify(root,upstream,image):
    if root.exists():raise ValueError('fresh private root required')
    root.mkdir(mode=0o700,parents=True)
    check_dependencies()
    home=prepare(root,upstream)
    os.environ['HERMES_DISABLE_LAZY_INSTALLS']='1'
    kb,kbc,_=native()
    with kbc.connect_closing():pass
    from hermes_cli.profiles import create_profile
    for name in ('tool-author','tool-reviewer'):
        create_profile(name,no_skills=True,description='Native SDK qualification only')
        write_json(home/'profiles'/name/'config.yaml',dict(model={'streaming':False,'context_length':65536},
            tools={'tool_search':{'enabled':'off'}},terminal={'backend':'fabriquinha','cwd':'/workspace'}))
    write_json(root/'project.json',config(image));project=Project.parse(config(image))
    store=Store(root/'private');board=Board(project);quality=Quality(project,store,Runner(project,store),board)
    workspace=root/'workspace';(workspace/'tests').mkdir(parents=True)
    (workspace/'app.py').write_text('VALUE = 1\n')
    (workspace/'tests/test_existing.py').write_text('import unittest, app\nclass Existing(unittest.TestCase):\n def test_type(self): self.assertIsInstance(app.VALUE,int)\n')
    for path in workspace.rglob('*'):path.chmod(0o777 if path.is_dir() else 0o666)
    workspace.chmod(0o777)
    baseline=store.capture(workspace)
    with kbc.connect_closing() as conn:
        task=kb.create_task(conn,title='Native agent tools and session qualification; not a release',
            body=json.dumps(dict(version=1,kind='tests',release='native-agent-fixture',inputs={'baseline':baseline})),
            assignee='tool-author',workspace_kind='dir',workspace_path=str(workspace),completion_contract='local-only')
        claimed=kb.claim_task(conn,task)
    def worker(run,mode):
        folder=root/'activities';folder.mkdir(exist_ok=True,mode=0o700)
        with (folder/(mode+'.log')).open('wb') as log:
            subprocess.run([sys.executable,str(Path(__file__).resolve()),'--root',str(root),'--upstream',str(upstream),
                '--activity',mode,'--task',task,'--run',str(run.number)],stdout=log,stderr=subprocess.STDOUT,
                env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},check=True,timeout=120)
    author=board.current(task,claimed.current_run_id);worker(author,'author')
    candidate=store.capture(workspace)
    assert (workspace/'app.py').read_text()=='VALUE = 1\n'
    with kbc.connect_closing() as conn:
        assert kb.schedule_task(conn,task,reason='Native session resume fixture',expected_run_id=author.number)
        assert kb.unblock_task(conn,task)
        claimed=kb.claim_task(conn,task)
    resumed=board.current(task,claimed.current_run_id);worker(resumed,'resume')
    assert store.capture(workspace)==candidate
    red=observe(lambda:quality.red(resumed,baseline,candidate))
    quality.handoff(resumed,'Read-only test review infrastructure fixture',{'red':red})
    with kbc.connect_closing() as conn:claimed=kb.claim_review_task(conn,task)
    reviewer=board.current(task,claimed.current_run_id);worker(reviewer,'review')
    assert store.capture(workspace)==candidate and store.tree(candidate)
    with kbc.connect_closing() as conn:
        assert kb.block_task(conn,task,reason='Infrastructure fixture finished; no model judgement or test approval',
                             expected_run_id=reviewer.number)
    assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project.namespace+'-tests').strip()
    proof=dict(native_agent=True,native_file_and_terminal_tools=True,real_docker=True,
        old_tests_and_product_protected=True,real_red=True,readonly_review=True,session_resume_new_process=True,
        reviewer_direct_write_terminal_and_admin_refused=True,continuous_dispatch=False,
        model_calls=0,synthetic_responses=True,delivery_approval=False,migration=False)
    write_json(root/'receipt.json',proof);print(json.dumps(proof,indent=2))


def archive_failed(root,error):
    """Only a fresh script-owned trial, after its sequential child has exited."""
    closed=[]
    if os.environ.get('HERMES_KANBAN_DB')==str(root/'home/kanban.db') and (root/'project.json').is_file():
        project=Project.parse(json.loads((root/'project.json').read_bytes()))
        store=Store(root/'private');board=Board(project);kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            rows=conn.execute("SELECT id,current_run_id FROM tasks WHERE status='running'").fetchall()
        for row in rows:
            cleanup='retired'
            try:Sandbox(project,store,board,board.current(row['id'],row['current_run_id'])).close()
            except Exception as failure:cleanup=type(failure).__name__
            with kbc.connect_closing() as conn:
                blocked=kb.block_task(conn,row['id'],reason='Native-agent qualification failed; evidence preserved, not approved',
                    expected_run_id=row['current_run_id'])
            closed.append(dict(task=row['id'],blocked=blocked,cleanup=cleanup))
    write_json(root/'failure.json',dict(qualification=False,model_calls=0,error=type(error).__name__,closed=closed))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image');parser.add_argument('--activity',choices=['author','resume','review'])
    parser.add_argument('--task');parser.add_argument('--run',type=int)
    args=parser.parse_args()
    if args.activity:activity(args.root.resolve(),args.upstream.resolve(),args.task,args.run,args.activity)
    else:
        root=args.root.resolve();fresh=not root.exists()
        try:qualify(root,args.upstream.resolve(),args.image)
        except Exception as error:
            if fresh and root.exists():archive_failed(root,error)
            raise
