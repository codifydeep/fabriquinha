"""Operator repair of exact blocked runtime contracts, no product edits."""
import json
from product_autonomy import Coordinator
from product_base_update import baseline_image
from product_docker_runner import DockerRunner
from product_case_inventory import inventory
from hermes_cli import kanban_db as kb

def main():
    c=Coordinator()
    if not (c.board/'MAINTENANCE').exists():raise PermissionError('maintenance required')
    if c.native.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone():raise PermissionError('active worker')
    task='t_3cfb0f6a';card=c.cfg['cards'][task]
    image=baseline_image(c.cfg,card['baseline_files'],{})
    runner=DockerRunner('/Users/weber/Documents/ChatGPT/Hermes/bootstrap/lobby-runtime/snapshots','lobby-ts')
    results={}
    for label,files,pinned in [('baseline',card['baseline_files'],image),('delivery',card['files'],card['validation_image'])]:
        r=runner(files,pinned);cases=inventory(r)
        if r['exit_code'] or any(v['status']!='passed' for v in cases.values()):raise PermissionError('repair verification failed: '+label)
        results[label]=dict(image=pinned,cases=len(cases),passed=True)
    c.register(task,dict(card,baseline_image=image))
    native=kb.get_task(c.native,task)
    if native.status=='blocked':
        if not kb.unblock_task(c.native,task,expected_block_event=967):raise PermissionError('revalidation event drift')
        kb.add_comment(c.native,task,'devops','Operator repaired baseline/image pairing and verified both full suites independently. No agent receipt or approval synthesized. Run fresh Green and full suite, then independent review. Consult work_knowledge and its sources; knowledge is not tool authority.')
    task='t_58938186';card=c.cfg['cards'][task];packet=json.loads((c.root/'team-packets'/f'{task}.json').read_text())
    packet['allowed_actions']=list(dict.fromkeys(packet['allowed_actions']+['request_prerequisite']))
    packet['prerequisite_contract']='request_prerequisite exact specification {capability: backend|frontend|quality,title,brief}. Propose the smallest evidenced source-level prerequisite with behavioral TDD and no weakening of tests/config. Independent review dispatches it to the specialist; actual PR integration creates fresh deploy/QA. No source edits or approval by operator. Read work_context/work_knowledge and verify relevant sources; explicitly distinguish applicable lessons from unrelated ones.'
    c.register(task,card,packet)
    if kb.get_task(c.native,task).status=='blocked':
        if not kb.unblock_task(c.native,task,expected_block_event=961):raise PermissionError('environment event drift')
        kb.add_comment(c.native,task,'devops','Reviewed prerequisite handoff now implemented. CTO may propose bounded specialist work; no automatic approval, deploy or homologation.')
    c.put('operator-recovery-verification-20260920',results)
    print(json.dumps(results))

if __name__=='__main__':main()
