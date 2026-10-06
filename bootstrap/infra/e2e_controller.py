"""Fixed, attempt-scoped GitHub and local deployment operations for the PoC.

No agent-supplied commands, refs, endpoints, Docker arguments or credentials.
The existing private controller alone invokes this module.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from urllib.parse import quote
from e2e_policy import BASELINE,NOTES,EDITABLE,validate,digest,baseline_matches

FIXTURE=Path(__file__).with_name('e2e_fixture')
REPO='codifydeep/truco-online'
ATTEMPT='rehearsal-e2e-20260916-ds1'
BASE='codex/rehearsal-e2e-base-20260916-ds1'
HEAD='codex/rehearsal-e2e-build-20260916-ds1'
PROJECT='truco-online-rehearsal-ds1'
CONTAINER=PROJECT+'-api'
PORT=18765


class E2E:
    def __init__(self,controller):
        self.c=controller
        path=self.c.store.root/'e2e-config.json'
        self.config=json.loads(path.read_text()) if path.exists() else None
        self.enabled=bool(self.config and self.config.get('attempt')==self.c.attempt==ATTEMPT)
        self.check_identity()
        if self.enabled:
            assert self.c.board.name==ATTEMPT
            self.c.db.execute('CREATE TABLE IF NOT EXISTS e2e_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            self.c.db.execute('CREATE TABLE IF NOT EXISTS e2e_audit(id INTEGER PRIMARY KEY,key TEXT,value TEXT,created_at REAL)')
            self.c.db.commit()

    def check_identity(self):
        if not self.c.attempt.startswith('rehearsal-e2e-'):
            return
        public_path=self.c.board/'e2e.json'
        public=json.loads(public_path.read_text()) if public_path.exists() else None
        private_path=self.c.store.root/'e2e-config.json'
        private=json.loads(private_path.read_text()) if private_path.exists() else None
        if (not self.enabled or private!=self.config or public!=private
                or self.c.board.name!=ATTEMPT):
            raise RuntimeError('e2e_identity_mismatch: controller/private/board configuration must match; technical operator repair required; ceo_required=false')
        return dict(ready=True,attempt=ATTEMPT,cards=private['cards'])

    def get(self,key,default=None):
        row=self.c.db.execute('SELECT value FROM e2e_state WHERE key=?',(ATTEMPT+':'+key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self,key,value):
        key=ATTEMPT+':'+key
        raw=json.dumps(value,sort_keys=True)
        self.c.db.execute('INSERT OR REPLACE INTO e2e_state VALUES(?,?)',(key,raw))
        self.c.db.execute('INSERT INTO e2e_audit(key,value,created_at) VALUES(?,?,?)',(key,raw,time.time()))
        self.c.db.commit()
        return value

    def gh(self,endpoint,method='GET',payload=None,missing_ok=False):
        if not endpoint.startswith('repos/'+REPO+'/'): raise PermissionError('repository outside rehearsal')
        command=['docker','run','--rm','-i','--network','bridge','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--pids-limit','64','--memory','192m','--cpus','0.5',
            '--label','com.docker.compose.project=hermes','--label','com.docker.compose.service=e2e-github',
            '--user','10000:10000','-e','GH_CONFIG_DIR=/gh','-e','GH_PROMPT_DISABLED=1',
            '--mount','type=volume,src=truco-online-hermes-data,dst=/gh,volume-subpath=home/.config/gh,readonly',
            '--entrypoint','/usr/bin/gh',self.c.image,'api',endpoint,'--method',method]
        if payload is not None: command+=['--input','-']
        result=subprocess.run(command,input=json.dumps(payload) if payload is not None else None,
            capture_output=True,text=True,timeout=35)
        if result.returncode:
            if missing_ok and 'HTTP 404' in result.stderr: return None
            raise RuntimeError('GitHub operation failed: '+result.stderr[-1200:])
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def api(self,suffix,**kwargs): return self.gh('repos/'+REPO+'/'+suffix,**kwargs)

    def commit(self,base_sha,files,message):
        tree=self.api('git/commits/'+base_sha)['tree']['sha']
        entries=[dict(path=name,mode='100644',type='blob',content=content) for name,content in sorted(files.items())]
        new=self.api('git/trees',method='POST',payload=dict(base_tree=tree,tree=entries))['sha']
        return self.api('git/commits',method='POST',payload=dict(message=message,tree=new,parents=[base_sha]))['sha']

    def workflow(self):
        return '''name: rehearsal-e2e
on:
  pull_request:
    branches: ["'''+BASE+'''"]
permissions:
  contents: read
concurrency:
  group: rehearsal-e2e-${{ github.event.pull_request.number }}
  cancel-in-progress: true
jobs:
  e2e-contract:
    if: github.event.pull_request.head.repo.full_name == github.repository && github.event.pull_request.head.ref == 'codex/rehearsal-e2e-build-20260916-ds1'
    runs-on: [self-hosted, linux, arm64, truco-local]
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          persist-credentials: false
      - name: Trusted base gate and isolated tests
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
          TEST_IMAGE: '''+self.c.image+'''
        run: |
          set -eu
          trusted=$(mktemp "${RUNNER_TEMP}/e2e-ci.XXXXXX.py")
          git show "${BASE_SHA}:rehearsal/ci.py" > "$trusted"
          python3 "$trusted"
'''

    def initialize(self):
        if os.environ.get('HERMES_KANBAN_TASK'): raise PermissionError('operator bootstrap only')
        old=self.api('git/ref/heads/'+BASE,missing_ok=True)
        if old:
            recorded=self.get('base') or self.get('base-intent')
            if not recorded or recorded['sha']!=old['object']['sha']: raise ValueError('unrecognized rehearsal base')
            return self.put('base',recorded)
        source=self.api('git/ref/heads/main')['object']['sha']
        files={'rehearsal/'+name:(FIXTURE/name).read_text() for name in ['service.py','test_regression.py','test_acceptance.py','ci.py','http_probe.py']}
        files.update({'rehearsal/policy.py':Path(__file__).with_name('e2e_policy.py').read_text(),
            'rehearsal/app.py':BASELINE,'.github/workflows/rehearsal-e2e.yml':self.workflow()})
        intent=self.get('base-intent')
        if intent is None:
            sha=self.commit(source,files,'chore: isolated E2E rehearsal base; no product release')
            intent=self.put('base-intent',dict(sha=sha,source_main=source,branch=BASE))
        self.api('git/refs',method='POST',payload=dict(ref='refs/heads/'+BASE,sha=intent['sha']))
        return self.put('base',intent)

    def workspace(self,task):
        path=Path(task['workspace_path']).resolve(strict=True)
        if path!=self.c.board/'workspaces'/task['id'] or path.is_symlink(): raise PermissionError('assigned scratch only')
        return path

    def files(self,task):
        root=self.workspace(task)
        result={}
        for name in EDITABLE:
            path=root/name
            if path.is_symlink(): raise PermissionError('symlinks forbidden')
            if path.exists():
                content=path.read_text(); validate(name,content); result[name]=content
        if not {'app.py','test_user.py'}<=result.keys(): raise ValueError('app.py and five user tests required')
        unexpected=[p.name for p in root.iterdir() if p.name not in EDITABLE|{'e2e-fault-ready.json'} and p.name!='__pycache__']
        if unexpected: raise ValueError('unexpected workspace files: '+str(unexpected))
        return result

    def fingerprint(self,files): return digest(json.dumps({n:files[n] for n in ['app.py','test_user.py']},sort_keys=True).encode())

    def published_diff(self,task):
        published=self.published()
        self.c.store.load(ATTEMPT,task['id'],published['revision'])
        frozen=self.c.store.path(ATTEMPT,task['id'],published['revision'])/'files'
        root=self.workspace(task); differences=[]
        for name in sorted(EDITABLE):
            live=root/name; source=frozen/name
            if live.is_symlink(): raise PermissionError('symlink forbidden')
            expected=digest(source.read_bytes()) if source.exists() else None
            actual=digest(live.read_bytes()) if live.exists() else None
            if expected!=actual: differences.append(dict(file=name,expected_sha=expected,actual_sha=actual))
        return differences

    def capture(self,task,run,files):
        with tempfile.TemporaryDirectory(dir=self.c.store.root,prefix='.candidate-') as tmp:
            root=Path(tmp)
            for name in ['test_regression.py','test_acceptance.py','service.py']:
                (root/name).write_bytes((FIXTURE/name).read_bytes())
            for name,content in files.items(): (root/name).write_text(content)
            return self.c.store.capture(root,attempt=ATTEMPT,task=task['id'],author=task['assignee'],run=run)

    def tests(self,task,revision):
        from review_controller import bounded_run
        result=bounded_run(['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--pids-limit','64','--memory','128m','--cpus','1',
            '--label','com.docker.compose.project=hermes','--label','com.docker.compose.service=e2e-tests',
            '--user','65534:65534','--mount',f'type=volume,src={self.c.volume},dst=/delivery,volume-subpath={ATTEMPT}/{task}/{revision}/files,readonly',
            '--workdir','/delivery','--entrypoint','/usr/bin/python3',self.c.image,'-B','-m','unittest','discover','-v'])
        counts=re.findall(r'^Ran (\d+) tests? in ',result.stdout,re.M)
        count=int(counts[0]) if len(counts)==1 else 0
        return dict(returncode=result.returncode,tests=count,passed=result.returncode==0 and count>=12,
            output=result.stdout[-32000:],revision=revision)

    def published(self):
        result=self.get('published')
        if not result: raise ValueError('no published delivery')
        return result

    def publish(self,task,run):
        files=self.files(task); fingerprint=self.fingerprint(files)
        green=self.get('green')
        if not green or green['fingerprint']!=fingerprint or not green['passed']: raise ValueError('matching Green required')
        if self.get('changes') and 'NOTES.md' not in files:
            return dict(block_required=True,category='unchanged_rework',passed=False,
                next_action='Add the requested NOTES.md before resubmission; no new PR commit or handoff was created.')
        content_hash=digest(json.dumps(files,sort_keys=True).encode())
        previous=self.get('published')
        if previous and previous.get('content_hash')==content_hash and previous['author_run']!=run:
            return dict(block_required=True,category='unchanged_resubmission',passed=False,next_action='No content change since previous delivery; diagnose instead of creating another revision.')
        if self.config.get('inject_worker_failure'):
            from review_board_read import board_read
            from coordination_reader import receipts
            fault=receipts(ATTEMPT)['fault'] or {}
            with board_read(self.c.board/'kanban.db') as db:
                failed=db.execute('SELECT outcome,ended_at FROM task_runs WHERE id=? AND task_id=?',(fault.get('run',-1),task['id'])).fetchone()
            if fault.get('state')!='killed' or not fault.get('observer_restart_observed') or run==fault.get('run') or not failed or not failed['ended_at'] or failed['outcome'] in ('review_requested','completed','scheduled'):
                return dict(wait_for_fault=True,passed=False,next_action='Call e2e_status; preserve code/tests. Controlled interruption must be evidenced, timeout is not proof.')
            if not self.get('worker-recovery') or self.get('worker-recovery').get('failed_run')!=fault['run']:
                self.put('worker-recovery',dict(failed_run=fault['run'],resumed_run=run,outcome=failed['outcome'],fingerprint=fingerprint))
        revision=self.capture(task,run,files)
        old=self.get('published')
        if old and old['revision']==revision: return old
        if old and old.get('merged'): raise PermissionError('cannot replace merged delivery')
        base=self.get('base'); ref=self.api('git/ref/heads/'+HEAD,missing_ok=True)
        parent=ref['object']['sha'] if ref else base['sha']
        key='publish-intent:'+revision
        intent=self.get(key)
        if old and parent!=old['head'] and (not intent or parent!=intent['head']): raise ValueError('rehearsal head changed externally')
        if not intent:
            sha=self.commit(parent,{'rehearsal/'+n:v for n,v in files.items()},'feat: '+ATTEMPT+' snapshot '+revision)
            intent=self.put(key,dict(head=sha,parent=parent))
        if ref:
            if ref['object']['sha']!=intent['head']:
                self.api('git/refs/heads/'+HEAD,method='PATCH',payload=dict(sha=intent['head'],force=False))
        else: self.api('git/refs',method='POST',payload=dict(ref='refs/heads/'+HEAD,sha=intent['head']))
        pulls=self.api('pulls?state=open&head='+quote('codifydeep:'+HEAD,safe='')+'&base='+quote(BASE,safe=''))
        pr=pulls[0] if pulls else self.api('pulls',method='POST',payload=dict(title='ENSAIO E2E — HTTP score, not Truco',head=HEAD,base=BASE,
            body='Isolated rehearsal. No product release. Immutable delivery '+revision+'. TDD evidence retained by Hermes controller.'))
        data=dict(revision=revision,head=intent['head'],base=base['sha'],pr=pr['number'],url=pr['html_url'],
            author=task['assignee'],author_run=run,reviewer='techlead',fingerprint=fingerprint,content_hash=content_hash,notes='NOTES.md' in files)
        self.c.db.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?)',(task['id'],run,revision,task['assignee'],'techlead')); self.c.db.commit()
        return self.put('published',data)

    def pull(self):
        published=self.published(); pr=self.api('pulls/'+str(published['pr']))
        if (pr['head']['sha']!=published['head'] or pr['head']['ref']!=HEAD or pr['base']['ref']!=BASE
            or pr['head']['repo']['full_name']!=REPO): raise ValueError('PR no longer matches scoped delivery')
        return pr

    def merge(self,task,run):
        published=self.published(); revision=published['revision']
        if not published['notes']: raise ValueError('request original author to add NOTES.md before approval')
        proof=self.get('review:'+str(run))
        if not proof or proof.get('revision')!=revision or not proof.get('passed'): raise ValueError('this reviewer must validate this revision')
        if task['assignee']!='techlead' or published['author']=='techlead': raise PermissionError('independent techlead required')
        pr=self.pull()
        if published.get('merged'):
            if not pr['merged'] or pr['merge_commit_sha']!=published['merge_sha']: raise ValueError('merge receipt mismatch')
            return published
        if pr.get('merged'):
            approval=self.get('approval')
            commit=self.api('git/commits/'+pr['merge_commit_sha'])
            if not approval or approval.get('head')!=published['head'] or approval.get('review_run')!=run or [p['sha'] for p in commit['parents']]!=[published['base'],published['head']]:
                raise ValueError('merged PR has no matching durable approval intent')
            published.update(merged=True,merge_sha=pr['merge_commit_sha'],approval=approval)
            self.c.db.execute('INSERT OR IGNORE INTO approvals VALUES(?,?,?,?,?)',(task['id'],revision,run,published['author'],task['assignee'])); self.c.db.commit()
            return self.put('published',published)
        if pr['base']['sha']!=published['base']: raise ValueError('base changed; new review required')
        checks=self.api('commits/'+published['head']+'/check-runs')['check_runs']
        checks=[c for c in checks if c['name']=='e2e-contract' and c['head_sha']==published['head'] and c['app']['slug']=='github-actions']
        latest=max(checks,key=lambda c:c['id']) if checks else None
        if latest and latest['status']=='completed' and latest['conclusion']!='success':
            check_id=latest['id']
            annotations=self.api('check-runs/'+str(check_id)+'/annotations')
            return self.put('last_operation_failure:'+task['id'],dict(category='ci_failed',pending=False,block_required=True,
                head=published['head'],check_id=check_id,conclusion=latest['conclusion'],url=latest.get('html_url'),
                annotations=[dict(path=a.get('path'),message=a.get('message')) for a in annotations[:10]],
                next_action='Real GitHub CI has failed, not a simulation or pending job. Tech Lead/CTO must diagnose the linked job. Do not retry merge or complete until a new successful check for this exact SHA exists.'))
        if not checks or max(checks,key=lambda c:c['id'])['conclusion']!='success':
            return dict(pending=True,next_action='CI not green; do not complete. Retry e2e_merge after e2e_status.',checks=[dict(status=c['status'],conclusion=c['conclusion']) for c in checks])
        approval=dict(approved=True,revision=revision,author=published['author'],reviewer=task['assignee'],review_run=run,head=published['head'])
        self.put('approval',approval)
        marker=f'Hermes E2E review {revision} run {run}'
        comments=self.api('issues/'+str(published['pr'])+'/comments?per_page=100')
        if not any(marker in c['body'] for c in comments):
            self.api('issues/'+str(published['pr'])+'/comments',method='POST',payload=dict(body=marker+'\nIndependent profile: techlead. Local isolated tests and CI passed. Not product homologation.'))
        self.api('statuses/'+published['head'],method='POST',payload=dict(state='success',context='hermes-independent-review',description='Exact snapshot reviewed by techlead'))
        result=self.api('pulls/'+str(published['pr'])+'/merge',method='PUT',payload=dict(sha=published['head'],merge_method='merge'))
        if not result.get('merged'): raise ValueError('GitHub refused merge')
        merge=result['sha']; commit=self.api('git/commits/'+merge)
        if [p['sha'] for p in commit['parents']]!=[published['base'],published['head']]: raise ValueError('merge parent race; deployment forbidden')
        published.update(merged=True,merge_sha=merge,approval=approval,checks=[dict(id=c['id'],conclusion=c['conclusion']) for c in checks])
        self.c.db.execute('INSERT OR IGNORE INTO approvals VALUES(?,?,?,?,?)',(task['id'],revision,run,published['author'],task['assignee'])); self.c.db.commit()
        return self.put('published',published)

    def runtime_image(self,baseline=False):
        published=self.published()
        sha=self.get('base')['sha'] if baseline else published['merge_sha']
        tag=PROJECT+':'+sha[:12]
        key='image:'+sha
        existing=self.get(key)
        if existing: return existing
        with tempfile.TemporaryDirectory(dir=self.c.store.root,prefix='.build-') as tmp:
            root=Path(tmp); (root/'service.py').write_bytes((FIXTURE/'service.py').read_bytes())
            code=BASELINE if baseline else (self.c.store.path(ATTEMPT,self.config['cards']['build'],published['revision'])/'files/app.py').read_text()
            (root/'app.py').write_text(code)
            (root/'Dockerfile').write_text('FROM '+self.c.image+'\nUSER 65534:65534\nWORKDIR /app\nCOPY app.py service.py /app/\nENTRYPOINT ["/usr/bin/python3","-B","/app/service.py"]\n')
            from review_controller import bounded_run
            result=bounded_run(['docker','build','--network','none','--label','com.docker.compose.project='+PROJECT,'--label','hermes.attempt='+ATTEMPT,'--label','hermes.commit='+sha,'-t',tag,str(root)],timeout=90)
            if result.returncode: raise ValueError('local build failed: '+result.stdout[-1200:])
        image_id=json.loads(subprocess.check_output(['docker','image','inspect',tag]))[0]['Id']
        return self.put(key,dict(tag=tag,id=image_id,commit=sha))

    def up(self,image):
        import yaml
        network=subprocess.run(['docker','network','inspect',PROJECT+'_default'],capture_output=True,text=True)
        if network.returncode==0 and (json.loads(network.stdout)[0].get('Labels') or {}).get('hermes.attempt')!=ATTEMPT:
            raise PermissionError('network belongs to another execution')
        existing=subprocess.run(['docker','inspect',CONTAINER],capture_output=True,text=True)
        if existing.returncode==0:
            labels=json.loads(existing.stdout)[0]['Config']['Labels'] or {}
            if labels.get('hermes.attempt')!=ATTEMPT: raise PermissionError('container name belongs to another execution')
        manifest={'services':{'api':dict(image=image['tag'],container_name=CONTAINER,read_only=True,user='65534:65534',
            cap_drop=['ALL'],security_opt=['no-new-privileges:true'],pids_limit=64,mem_limit='128m',cpus=0.5,
            ports=[f'127.0.0.1:{PORT}:8080'],environment={'APP_COMMIT':image['commit']},
            labels={'hermes.attempt':ATTEMPT,'hermes.commit':image['commit']},
            healthcheck=dict(test=['CMD','/usr/bin/python3','-c','import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/health",timeout=2)'],interval='5s',timeout='3s',retries=6))},
            'networks':{'default':{'internal':False,'labels':{'hermes.attempt':ATTEMPT}}}}
        path=self.c.store.root/'e2e-compose.yaml'; path.write_text(yaml.safe_dump(manifest))
        from review_controller import bounded_run
        result=bounded_run(['docker','compose','-p',PROJECT,'-f',str(path),'up','-d','--no-build'],timeout=60)
        if result.returncode: raise ValueError('scoped compose failed: '+result.stdout[-1200:])
        for _ in range(10):
            inspect=json.loads(subprocess.check_output(['docker','inspect',CONTAINER]))[0]
            if inspect['Image']!=image['id'] or inspect['Config']['Labels'].get('hermes.commit')!=image['commit']:
                raise ValueError('runtime image differs from approved build')
            if inspect['State'].get('Health',{}).get('Status')=='healthy': return
            time.sleep(1)
        raise ValueError('rehearsal service unhealthy')

    def http(self,baseline=False):
        published=self.published(); expected=self.get('base')['sha'] if baseline else published['merge_sha']
        image=self.get('image:'+expected)
        inspect=json.loads(subprocess.check_output(['docker','inspect',CONTAINER]))[0]
        if inspect['Image']!=image['id'] or inspect['Config']['Labels'].get('hermes.commit')!=expected: raise ValueError('wrong runtime commit')
        from http_probe_runner import run_probe
        receipt=run_probe(self.c.image,CONTAINER,expected,baseline,(FIXTURE/'http_probe.py').read_text(),PROJECT,
            lambda state:self.put('http-probe:'+state['name'],state))
        if not receipt.get('passed') or receipt['commit']!=expected or receipt['checks']!=(1 if baseline else 10): raise ValueError('invalid HTTP probe result')
        receipt=dict(receipt,image_id=image['id'],url=f'http://127.0.0.1:{PORT}')
        if not baseline and os.environ.get('E2E_HOST_RECEIPT'):
            from host_receipt import wait_receipt
            host=wait_receipt(os.environ['E2E_HOST_RECEIPT'],expected,f'http://127.0.0.1:{PORT}',
                lambda detail:self.put('host-receipt-observation',detail))
            receipt['host_access']=host
        return receipt

    def deploy(self):
        published=self.published()
        if not published.get('merged') or not published.get('approval'): raise ValueError('reviewed merge required')
        self.pull()
        receipt=self.get('deploy')
        if receipt:
            self.http(); return receipt
        baseline=self.runtime_image(True); candidate=self.runtime_image(False)
        phases={}
        for name,image,is_baseline in [('baseline',baseline,True),('first',candidate,False),('rollback',baseline,True),('final',candidate,False)]:
            key='deploy-phase:'+published['merge_sha']+':'+name
            receipt=self.get(key)
            if receipt:
                phases[name]=receipt; continue
            # A failed host wait must not recreate an already healthy runtime.
            from review_controller import bounded_run
            found=bounded_run(['docker','inspect',CONTAINER],timeout=10)
            current=json.loads(found.stdout)[0] if found.returncode==0 else {}
            if not (current.get('Image')==image['id'] and current.get('State',{}).get('Health',{}).get('Status')=='healthy'
                    and current.get('Config',{}).get('Labels',{}).get('hermes.commit')==image['commit']):
                self.up(image)
            phases[name]=self.put(key,self.http(is_baseline))
        return self.put('deploy',dict(commit=published['merge_sha'],baseline=phases['baseline'],first=phases['first'],
            rollback=phases['rollback'],final=phases['final'],passed=True))

    def recovery_evidence(self):
        from review_board_read import board_read
        from coordination_reader import receipts
        evidence=receipts(ATTEMPT)
        fault=evidence['fault'] or {}
        notification=evidence['notification']; sent=evidence['sent_at']
        recovery=self.get('worker-recovery')
        if not recovery or fault.get('state')!='killed' or fault.get('run')!=recovery['failed_run'] or not fault.get('observer_restart_observed') or not notification or not sent:
            raise ValueError('recovery/outbox/observer-restart evidence incomplete; no E2E success')
        return dict(worker=recovery,fault=fault,notification_retried=True,notification_delivered_at=sent)

    def handle(self,task,is_review,request):
        role=next((name for name,tid in self.config['cards'].items() if tid==task['id']),None)
        if role is None:
            match=re.match(r'(?:INCIDENT|SPIKE)-(t_[A-Za-z0-9]+)',task['title'])
            if not match or match[1] not in self.config['cards'].values() or task['assignee'] not in ('cto','techlead') or request['operation'] not in ('diagnose','e2e_status'):
                raise PermissionError('task outside registered E2E graph')
            from review_board_read import board_read
            with board_read(self.c.board/'kanban.db') as db:
                source=db.execute('SELECT * FROM tasks WHERE id=?',(match[1],)).fetchone()
            differences=self.published_diff(dict(source)) if match[1]==self.config['cards']['build'] and self.get('published') else []
            self.put('diagnostic:'+str(request['run']),dict(source=match[1],differences=differences,at=time.time()))
            return dict(category='e2e_technical_failure',source=dict(source),published=self.get('published'),
                differences=differences,experiment='Fixed snapshot hash comparison executed; evidence saved by controller. No terminal or scratch result file required.',
                green=self.get('green'),deploy=self.get('deploy'),last_operation_failure=self.get('last_operation_failure:'+match[1]),can_resume=False,ceo_required=False,
                next_action='Record precise failed operation and evidence in this technical incident. No blind reset, no approval, no external administrative actions. A controller correction or new evidence is required before resuming.')
        expected={'build':'backend_data','deploy':'devops','qa':'quality_security'}[role]
        reviewer={'build':'techlead','deploy':'quality_security','qa':'techlead'}[role]
        if task['assignee']!=(reviewer if is_review else expected): raise PermissionError('wrong E2E role')
        op=request['operation']; run=request['run']
        if op=='e2e_review_validate':
            if not is_review or role=='build': raise PermissionError('deployment or QA reviewer only')
            request=dict(request,revision=self.published()['merge_sha']); op='validate'
        if op in ('e2e_status','inspect'):
            published=self.get('published')
            delivery=dict(published or {})
            if role!='build' and published: delivery['revision']=published.get('merge_sha')
            if is_review and role!='build':
                return dict(role=role,mode='review',delivery={'revision':published['merge_sha']},
                    review_target={'kind':'deployed_merge_commit','revision':published['merge_sha']},
                    deployment=self.get('deploy'),
                    next_operation={'tool':'e2e_review_validate','arguments':{}},
                    next_action='Validate only this deployed merge commit; after passed=true call kanban_complete. Historical Red/Green snapshots are not review targets.')
            content=None
            if is_review and role=='build' and published:
                root=self.c.store.path(ATTEMPT,self.config['cards']['build'],published['revision'])/'files'
                self.c.store.load(ATTEMPT,self.config['cards']['build'],published['revision'])
                content={p.name:p.read_text() for p in root.iterdir() if p.is_file()}
            return dict(role=role,mode='review' if is_review else 'implementation',
                delivery=delivery,immutable_files=content,
                red=self.get('red'),green=self.get('green'),published=self.get('published'),deploy=self.get('deploy'),qa=self.get('qa'),
                notes_required=NOTES,files=self.files(task) if role=='build' and not is_review and (self.workspace(task)/'test_user.py').exists() else None)
        if op=='e2e_edit_check':
            if is_review or role!='build': raise PermissionError('author only')
            validate(request['path'],request['content'])
            published=self.get('published'); changes=self.get('changes')
            if request['path']=='NOTES.md' and not (published and changes and changes.get('revision')==published['revision'] and not published.get('notes')):
                raise PermissionError('notes require a formal changes request for the current published revision; next tool: kanban_request_review(reviewer="techlead")')
            if self.get('green') and request['path']!='NOTES.md': raise PermissionError('accepted code/tests frozen; only notes rework allowed')
            return dict(allowed=True)
        if op in ('e2e_restore_published','e2e_restore_confirm'):
            if is_review or role!='build': raise PermissionError('original author only')
            published=self.published()
            if self.get('changes',{}).get('revision')==published['revision']:
                raise PermissionError('active requested rework must not be discarded')
            differences=self.published_diff(task)
            frozen=self.c.store.path(ATTEMPT,task['id'],published['revision'])/'files'
            files={n:(frozen/n).read_text() for n in EDITABLE if (frozen/n).exists()}
            if op=='e2e_restore_confirm':
                if differences: raise ValueError('restore incomplete: '+json.dumps(differences))
                return self.put('restored:'+str(run),dict(revision=published['revision'],run=run,passed=True))
            backup={n:(self.workspace(task)/n).read_text() for n in EDITABLE if (self.workspace(task)/n).exists()}
            backup_id='workspace-backup:'+task['id']+':'+digest(json.dumps(backup,sort_keys=True).encode())
            self.put(backup_id,dict(files=backup,differences=differences,revision=published['revision'],run=run))
            return dict(files=files,remove=sorted(EDITABLE-set(files)),backup_id=backup_id,revision=published['revision'])
        if op=='e2e_test':
            if is_review or role!='build': raise PermissionError('author test only')
            stage=request.get('stage')
            if stage not in ('red','green'): raise PermissionError('fixed stages only')
            files=self.files(task); fingerprint=self.fingerprint(files)
            old=self.get(stage)
            if old:
                if old['fingerprint']!=fingerprint: raise ValueError('historical '+stage+' cannot be replaced')
                return old
            if stage=='red' and not baseline_matches(files['app.py']):
                key='last_operation_failure:'+task['id']
                previous=self.get(key,{})
                count=previous.get('count',0)+1 if previous.get('fingerprint')==fingerprint and previous.get('run')==run else 1
                return self.put(key,dict(category='baseline_contract_mismatch',operation='e2e_test',stage='red',
                    task=task['id'],run=run,count=count,fingerprint=fingerprint,
                    expected=BASELINE,actual=files['app.py'],expected_sha=digest(BASELINE.encode()),
                    actual_sha=digest(files['app.py'].encode()),accepted=False,passed=False,
                    block_required=count>=2,next_action='Restore the baseline function returning None before Red. Formatting is allowed. Repeated identical rejection requires technical diagnosis, not more runtime.'))
            red=self.get('red')
            if stage=='green' and (not red or red['tests_sha']!=digest(files['test_user.py'].encode())): raise ValueError('preserve tests from accepted Red')
            revision=self.capture(task,run,files); result=self.tests(task['id'],revision)
            if stage=='red' and not (result['returncode']!=0 and result['tests']>=12 and 'FAILED (failures=' in result['output'] and 'errors=' not in result['output']): raise ValueError('Red needs real assertion failures, not syntax/import errors')
            if stage=='green' and not result['passed']: return result
            return self.put(stage,dict(result,accepted=True,fingerprint=fingerprint,tests_sha=digest(files['test_user.py'].encode()),run=run))
        if op=='e2e_submit':
            if is_review or role!='build': raise PermissionError('author submission only')
            return self.publish(task,run)
        if op=='freeze':
            if is_review or request['reviewer']!=reviewer: raise PermissionError('canonical independent reviewer required')
            if role=='build':
                published=self.published()
                if published['author_run']!=run and self.get('restored:'+str(run),{}).get('revision')!=published['revision']: raise ValueError('e2e_submit or verified restoration required for this run')
                self.files(task)  # Validate scope; snapshot identity also includes its original run.
                differences=self.published_diff(task)
                if differences:
                    detail=dict(category='workspace_changed_after_publication',differences=differences,next_tool='e2e_restore_published',ceo_required=False)
                    self.put('last_operation_failure:'+task['id'],detail)
                    raise ValueError(json.dumps(detail))
                return dict(revision=published['revision'],author=expected,reviewer=reviewer,head=published['head'])
            receipt=self.get('deploy' if role=='deploy' else 'qa')
            if not receipt or not receipt.get('passed'): raise ValueError('fixed execution receipt required')
            return dict(revision=self.published()['merge_sha'],author=expected,reviewer=reviewer,parent_revision=self.published()['revision'])
        if op=='validate':
            if not is_review: raise PermissionError('review only')
            published=self.published(); revision=published['revision'] if role=='build' else published['merge_sha']
            if request.get('revision')!=revision:
                detail=dict(category='stale_review_revision',expected_revision=revision,received_revision=request.get('revision'),
                    next_operation={'tool':'review_validate','arguments':{'revision':revision}})
                self.put('last_operation_failure:'+task['id'],detail)
                raise ValueError(json.dumps(detail))
            from http_probe_runner import ProbeFailure
            try: result=self.tests(self.config['cards']['build'],revision) if role=='build' else self.http()
            except ProbeFailure as exc:
                self.put('last_operation_failure:'+task['id'],exc.detail)
                return dict(exc.detail,passed=False)
            return self.put('review:'+str(run),dict(result,revision=revision,reviewer=reviewer,role=role))
        if op=='decision':
            proof=self.get('review:'+str(run))
            if not is_review or role!='build' or not proof or not proof['passed'] or proof['revision']!=self.published()['revision']: raise ValueError('validate current review before requesting changes')
            if self.published()['notes']: raise ValueError('notes already verified; unsupported repeated rejection')
            self.put('changes',dict(run=run,revision=proof['revision']))
            return dict(reason='[E2E_DOCUMENTATION] Add only NOTES.md, exactly: '+NOTES+' Use e2e_write, e2e_submit, then kanban_request_review. Preserve all code and tests.')
        if op=='e2e_merge':
            if not is_review or role!='build': raise PermissionError('build reviewer only')
            if not self.get('changes'): raise ValueError('required review/rework cycle missing')
            return self.merge(task,run)
        if op=='e2e_deploy':
            if is_review or role!='deploy': raise PermissionError('devops implementation only')
            from host_receipt import HostReceiptPending
            try: return self.deploy()
            except HostReceiptPending as exc:
                self.put('last_operation_failure:'+task['id'],exc.detail)
                return dict(exc.detail,passed=False)
        if op=='e2e_verify':
            if is_review or role!='qa': raise PermissionError('QA implementation only')
            if not self.get('deploy') or not self.get('approved:deploy'): raise ValueError('independently reviewed deployment required')
            return self.put('qa',dict(self.http(),passed=True,run=run,profile=expected))
        if op=='approve':
            if not is_review: raise PermissionError('independent review only')
            published=self.published()
            if role=='build':
                if not published.get('merged') or published['approval']['review_run']!=run: raise ValueError('e2e_merge required before completion')
                return published['approval']
            proof=self.get('review:'+str(run))
            if not proof or not proof.get('passed') or proof['revision']!=published['merge_sha']: raise ValueError('current post-deploy validation required')
            recovery=self.recovery_evidence() if role=='qa' and self.config.get('inject_worker_failure') else None
            approval=dict(approved=True,revision=published['merge_sha'],author=expected,reviewer=reviewer,review_run=run,
                summary='E2E rehearsal '+role+' verified at '+published['merge_sha']+'. Not Truco homologation.')
            self.put('approved:'+role,approval)
            if role=='qa': self.put('result',dict(scope='isolated_e2e',delivery=published,deploy=self.get('deploy'),qa=self.get('qa'),approval=approval,
                product_released=False,recovery=recovery,passed=True))
            return approval
        raise PermissionError('operation not allowed in E2E mode')
