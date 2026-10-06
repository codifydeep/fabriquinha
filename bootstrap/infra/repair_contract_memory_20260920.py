"""Register repaired capabilities on exact preserved incidents; no approvals."""
import json
from product_autonomy import Coordinator
from hermes_cli import kanban_db as kb
from product_memory import curate

def main():
    c=Coordinator()
    if not (c.board/'MAINTENANCE').exists():raise PermissionError('maintenance required')
    if c.native.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone():raise PermissionError('active worker')
    task='t_bbc19922';card=c.cfg['cards'][task];packet=json.loads((c.root/'team-packets'/f'{task}.json').read_text())
    target=c.cfg['cards'][packet['target_task']]
    if not target.get('prerequisite_for'):raise PermissionError('not an implementation prerequisite')
    packet['allowed_actions']=list(dict.fromkeys(packet['allowed_actions']+['revise_technical_contract']))
    packet['technical_contract_revision_allowed']=True
    packet['technical_contract_rules']='revise_technical_contract accepts exact {target_task,draft_sha256,brief}. Brief is a complete replacement technical acceptance contract; historical briefs remain archived. Independently review removal of unnecessary implementation prescriptions only, never product scope, tests, permissions or runtime behavior. Trusted deployment runner starts node directly with APP_ENTRY, PORT=8080, HOST=0.0.0.0; it does not execute npm start. Verify whether package start is essential to the runnable-entry prerequisite. No approval or amendment has been made by operator.'
    c.register(task,card,packet)
    if kb.get_task(c.native,task).status=='blocked':
        if not kb.unblock_task(c.native,task,expected_block_event=1178):raise PermissionError('contract block occurrence drift')
        kb.add_comment(c.native,task,'devops','Technical contract refinement now executable under independent review. Preserve source, tests and immutable TDD evidence. No protected write grant.')
    # Refresh actual integrated-commit evidence before resuming its curators.
    curate(c)
    for task,event in [('t_dc23414a',1332),('t_876852c8',1337)]:
        native=kb.get_task(c.native,task)
        if native.status!='blocked':continue
        packet=json.loads((c.root/'team-packets'/f'{task}.json').read_text())
        source=packet.get('proposal_source',{}).get('id')
        if source and c.get('knowledge:'+source+':replacement'):continue
        packet['evidence_update']='work_evidence now resolves PR:<number>@<exact merge SHA> from controller-owned, current-attempt INTEGRATED receipts. Historical card text describes its original phase, not current integration status. Citation-only corrections are allowed in promote_knowledge and require fresh independent review; all other entry fields remain immutable. Verify evidence; do not infer homologation.'
        c.register(task,c.cfg['cards'][task],packet)
        if not kb.unblock_task(c.native,task,expected_block_event=event):raise PermissionError('knowledge block occurrence drift')
        kb.add_comment(c.native,task,'devops','Integration evidence reader installed. Resume sourced curation; no knowledge approved by operator.')
    task='t_df4807a3';native=kb.get_task(c.native,task)
    if native.status=='blocked':
        event=c.native.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(task,)).fetchone()
        if 'Operator maintenance' not in event[1]:raise PermissionError('unexpected interrupted card state')
        packet=json.loads((c.root/'team-packets'/f'{task}.json').read_text())
        packet['execution_clarification']='You are the PROPOSER in implementation mode, not the reviewer. Read sources with work_evidence; submit team_propose(action=promote_knowledge,reason,specification=entry). A different profile receives team_decide in its subsequent review run. Do not repeatedly search for reviewer-only tools. PR evidence now resolves exact registered commits. Stop after the durable proposal handoff.'
        c.register(task,c.cfg['cards'][task],packet)
        if not kb.unblock_task(c.native,task,expected_block_event=event[0]):raise PermissionError('interrupted card resume refused')
    (c.board/'MAINTENANCE').unlink();(c.board/'DRAIN').unlink()
    print('contract and evidence repairs registered; dispatch resumed')

if __name__=='__main__':main()
