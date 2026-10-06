"""Idempotent operator migration after backup, never a worker capability."""
import json,sqlite3,os
from pathlib import Path
from product_policy import VERSION,ROLES
from product_manifest import manifest,profile_check
from product_workspace import digest
from product_autonomy import atomic

def refresh_maintenance_packets():
    from product_autonomy import Coordinator
    from hermes_cli import kanban_db as kb
    c=Coordinator()
    for tid,card in list(c.cfg['cards'].items()):
        if card.get('capability')!='test_maintenance' or card.get('maintenance_validator')=='v2':continue
        packet=json.loads((c.root/'team-packets'/f'{tid}.json').read_text());target=packet['target_task']
        row=c.private.execute('SELECT files FROM product_drafts WHERE task=?',(target,)).fetchone()
        if not row or digest(json.loads(row[0]))!=packet['draft_sha256']:continue
        source=c.cfg['cards'][target];files=json.loads(row[0])
        removable=[n for n,v in files.items() if not v.strip() and n not in source.get('files',{}) and n not in source.get('protected',[])]
        packet.update(removable_empty_artifacts=removable,
            validator_update='team_validate now returns actual failed suite/case diagnostics. Never infer baseline failure from the contract narrative. Optional specification.remove_empty lists only controller-verified new empty artifacts. It cannot remove a pre-existing test or any nonempty file. A proposal lacking required cleanup must be returned to its original author, not approved or silently patched.')
        c.register(tid,dict(card,maintenance_validator='v2'),packet)
        native=kb.get_task(c.native,tid)
        if native.status=='blocked' and native.assignee==card['reviewer']:
            event=c.native.execute("SELECT id FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(tid,)).fetchone()
            if not kb.unblock_task(c.native,tid,expected_block_event=event[0]):raise PermissionError('review resume refused')
            kb.add_comment(c.native,tid,'devops','Validator v2 installed: structured executed diagnostics and reviewed cleanup of verified new empty artifacts. Resume independent review; no approval or product edits by operator.')

def refresh_governance_validator():
    from product_autonomy import Coordinator
    from hermes_cli import kanban_db as kb
    c=Coordinator()
    for tid,card in list(c.cfg['cards'].items()):
        if card.get('scope')!='coordination' or card.get('governance_validator')=='v1':continue
        packet=json.loads((c.root/'team-packets'/f'{tid}.json').read_text())
        if packet.get('allowed_actions')!=['publish_governance']:continue
        packet['validation_operation']='team_validate(proposal_sha256) now supports publish_governance. It runs seven adversarial integrity-guard cases against this frozen proposal in a no-network, no-credentials Docker sandbox. Approval requires a passing receipt in this exact review run. Capability remains platform; do not misclassify governance publication as maintain_tests. No permission was delegated by model text.'
        c.register(tid,dict(card,governance_validator='v1'),packet)
        native=kb.get_task(c.native,tid)
        if native.status=='blocked' and native.assignee==card['reviewer']:
            event=c.native.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(tid,)).fetchone()
            if event and 'test-maintenance review scope' in event[1]:
                if not kb.unblock_task(c.native,tid,expected_block_event=event[0]):raise PermissionError('governance reviewer resume refused')
                kb.add_comment(c.native,tid,'devops','Fixed isolated governance validator installed. Resume exact proposal review; no operator approval and no scope bypass.')

def main():
    root=Path('/control');board=Path('/board')
    if not (board/'MAINTENANCE').is_file():raise PermissionError('maintenance window required')
    with sqlite3.connect(board/'kanban.db') as db:
        if db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone():raise PermissionError('active worker; migration refused')
    for role in ROLES:profile_check('/profiles',role)
    refresh_maintenance_packets()
    refresh_governance_validator()
    cfg=json.loads((root/'config.json').read_text())
    cfg.update(process_policy=VERSION,runtime_manifest_sha256=digest(manifest()),dispatch_slots=cfg.get('dispatch_slots',1))
    image=os.environ.get('CONTROL_VALIDATION_IMAGE')
    if image:
        import re
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):raise ValueError('pinned control image required')
        cfg['control_validation_image']=image
    # Existing snapshots, reviews and TDD receipts are never converted to new proof.
    atomic(root/'runtime-manifest.json',manifest());atomic(board/'runtime-manifest.json',manifest())
    atomic(root/'config.json',cfg);atomic(board/'product-adapter.json',cfg)
    print(json.dumps(dict(policy=VERSION,manifest=cfg['runtime_manifest_sha256'],profiles=len(ROLES),dispatch_slots=cfg['dispatch_slots'],old_receipts_changed=False)))
if __name__=='__main__':main()
