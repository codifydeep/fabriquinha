"""Private isolated controller, explicitly configured; never edits live setup."""
import json,os,socketserver,sqlite3
from pathlib import Path
from hermes_cli import kanban_db as kb
from product_claim import NativeClaim
from product_workspace import Workspace
from product_tdd import TDD
from product_docker_runner import DockerRunner
from product_worker_service import WorkerService

def main():
    root=Path(os.environ['PRODUCT_CONTROL_ROOT']).resolve(strict=True)
    settings=json.loads((root/'config.json').read_text())
    from product_manifest import verify
    policy=verify(settings)
    board=Path(settings['board']).resolve(strict=True)
    public=json.loads((board/'product-adapter.json').read_text())
    if public['attempt']!=settings['attempt'] or public['cards']!=settings['cards']:raise PermissionError('registration drift')
    native=kb.connect(board/'kanban.db');db=sqlite3.connect(root/'controller.db')
    w=Workspace(db,NativeClaim(board,settings['attempt'],settings['cards']))
    for task,card in settings['cards'].items():
        if card.get('scope') in ('pr_review','coordination'):continue
        if not db.execute('SELECT 1 FROM product_drafts WHERE attempt=? AND task=?',(settings['attempt'],task)).fetchone():
            w.seed(settings['attempt'],task,card['author'],card['base'],card['files'],card['protected'],card['reviewer'])
    service=WorkerService(w,TDD(w,settings['image']),DockerRunner(settings['snapshot_root'],settings.get('runner','node')),native)
    from product_pr_review import PRReview
    pr_review=PRReview(root,w.claim,native,db)
    from product_team import Team
    team=Team(root,w.claim,native,db,runner=service.runner,governance_runner=DockerRunner(settings['snapshot_root'],'governance'),governance_image=settings.get('control_validation_image'))
    from product_impediments import Impediments
    impediments=Impediments(db,w.claim,native)
    from product_validation_jobs import start
    from coordination_store import CoordinationStore
    ledger=CoordinationStore(root/'coordination.db')
    if not ledger.db.execute('SELECT 1 FROM attempts WHERE id=?',(settings['attempt'],)).fetchone():
        ledger.create_attempt(settings['attempt'],board.name,settings.get('release','adapter-trial'))
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                raw=self.rfile.readline(65537)
                if len(raw)>65536:raise ValueError('request too large')
                request=json.loads(raw)
                if request=={'operation':'product_readiness'}:
                    result=dict(ready=True,attempt=settings['attempt'],cards=list(settings['cards']),
                        policy=policy,
                        product_enabled=settings.get('scope')=='truco-lobby' and not (board/'MAINTENANCE').exists())
                elif request.get('operation')=='work_recall':
                    from product_work_recall import recall
                    result=recall(db,w.claim,request)
                elif request.get('operation') in ('work_context','work_evidence','work_knowledge','work_knowledge_history','work_checkpoint','work_lesson','work_personal'):
                    from product_memory import handle
                    result=handle(db,w.claim,request)
                elif request.get('operation')=='product_report_impediment':result=impediments.handle(request)
                elif settings['cards'].get(request.get('task'),{}).get('scope')=='coordination':result=team.handle(request)
                elif settings['cards'].get(request.get('task'),{}).get('scope')=='pr_review':result=pr_review.handle(request)
                else:
                    service.tdd.image=settings['cards'].get(request.get('task'),{}).get('validation_image',settings['image'])
                    result=service.handle(request)
            except Exception as exc:
                result=dict(error=type(exc).__name__,detail=str(exc))
                if hasattr(exc,'diagnostic'):result['diagnostic']=exc.diagnostic
            self.wfile.write(json.dumps(result).encode()+b'\n')
    socket=Path(os.environ.get('PRODUCT_CONTROL_SOCKET','/run/review-control/controller.sock'))
    # Exclusive lifetime lock makes stale socket cleanup safe after restart.
    import fcntl
    lock=(root/'controller.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    start(root,settings)
    from product_deployment_jobs import start as start_deployments
    start_deployments(root,settings)
    if socket.exists():
        import stat
        if not stat.S_ISSOCK(socket.lstat().st_mode):raise RuntimeError('unexpected socket path')
        socket.unlink()
    socket.parent.mkdir(parents=True,exist_ok=True)
    with socketserver.UnixStreamServer(str(socket),Handler) as server:
        socket.chmod(0o666);server.timeout=1
        while True:
            # Coordinator writes canonical private registration, then public projection.
            fresh=json.loads((root/'config.json').read_text())
            projected=json.loads((board/'product-adapter.json').read_text())
            if fresh==projected and fresh['attempt']==settings['attempt']:
                settings['cards']=fresh['cards'];w.claim.cards=fresh['cards']
            server.handle_request()
            try:
                service.recover();pr_review.recover();team.recover();impediments.recover();service.export_notifications(ledger,settings.get('chat_id'))
            except Exception as exc:
                print(json.dumps(dict(event='recovery_blocked',category=type(exc).__name__)),flush=True)

if __name__=='__main__':main()
