import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_controller import Controller
from planning_flow import ROLES, SECTIONS, allowed, claim_allowed


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.board = Path(self.temp.name) / 'board'; self.board.mkdir()
        self.private = Path(self.temp.name) / 'private'; self.private.mkdir()
        self.db = sqlite3.connect(self.board / 'kanban.db'); self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE tasks(id,status,current_run_id,claim_lock,assignee); '
                             'CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id,run_id,kind,payload);')
        self.brief = 'approved brief'; self.digest = hashlib.sha256(self.brief.encode()).hexdigest()
        self.data = dict(attempt='planning-test', brief_sha256=self.digest, cards={
            't_' + role: dict(role=role, author=people[0], reviewer=people[1], parents=[], objective=role)
            for role, people in ROLES.items()})
        (self.board / 'planning.json').write_text(json.dumps(self.data))
        (self.private / 'planning-config.json').write_text(json.dumps(self.data))
        (self.private / 'planning-brief.md').write_text(self.brief)
        self.c = Controller(self.board, self.private, 'planning-test', 'unused', 'unused')
        self.addCleanup(lambda: self.c.db.close())

    def activate(self, role='stories', run=1, review=False):
        author, reviewer = ROLES[role]; tid = 't_' + role
        self.db.execute('DELETE FROM tasks WHERE id=?', (tid,))
        self.db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)', (tid, 'running', run, 'lock', reviewer if review else author))
        self.db.execute('INSERT INTO task_events(task_id,run_id,kind,payload) VALUES(?,?,?,?)',
                        (tid, run, 'claimed', json.dumps(dict(source_status='review' if review else 'ready'))))
        self.db.commit()
        self.request = dict(task=tid, run=run, claim='lock')

    def op(self, op, **args):
        return self.c.handle(dict(self.request, operation=op, **args))

    def content(self, extra=''):
        return self.digest + '\n' + '\n'.join('## ' + s + '\nConcrete planning decision and verification.' for s in SECTIONS) + extra

    def freeze(self, role='stories'):
        self.op('planning_write', content=self.content())
        return self.op('freeze', reviewer=ROLES[role][1])['revision']

    def test_all_independent_mappings_and_semantic_changes(self):
        for role in ROLES:
            self.activate(role); old = self.freeze(role)
            self.activate(role, 2, True)
            with self.assertRaises(PermissionError): self.op('planning_write', content=self.content('bad'))
            with self.assertRaises(ValueError): self.op('approve', revision=old)
            self.op('validate', revision=old)
            self.assertTrue(self.op('decision', revision=old, reason='Document must clarify the concurrent room join conflict.')['reason'].startswith('[PLAN_CHANGES]'))
            self.activate(role, 3)
            self.op('planning_write', content=self.content('Changes made after independent review.'))
            fresh = self.op('freeze', reviewer=ROLES[role][1])['revision']
            self.assertNotEqual(old, fresh)
            self.activate(role, 4, True)
            with self.assertRaises(ValueError): self.op('approve', revision=old)
            self.op('validate', revision=fresh)
            receipt = self.op('approve', revision=fresh)
            self.assertTrue(receipt['approved']); self.assertFalse(receipt['implementation_allowed'])
            self.assertEqual(receipt['reviewer'], ROLES[role][1])
            self.c.store.load('planning-test', 't_' + role, old)

    def test_restart_between_snapshot_and_handoff(self):
        self.activate(); first = self.freeze()
        self.c.db.close()
        self.c = Controller(self.board, self.private, 'planning-test', 'unused', 'unused')
        self.assertEqual(first, self.op('freeze', reviewer='techlead')['revision'])
        with self.assertRaises(PermissionError): self.op('planning_write', content=self.content('overwrite'))

    def test_identity_tampering_fails_closed(self):
        self.activate()
        (self.board / 'planning.json').write_text('{}')
        with self.assertRaises(PermissionError): self.op('planning_read')

    def test_wrong_author_and_review_claim(self):
        self.activate(); self.freeze()
        self.activate(run=2, review=True)
        self.db.execute("UPDATE tasks SET assignee='produto'"); self.db.commit()
        with self.assertRaises(PermissionError): self.op('inspect')

    def test_unknown_cards_and_tools_denied(self):
        with patch.dict(os.environ, HERMES_KANBAN_DB=str(self.board / 'kanban.db')):
            self.assertEqual(allowed(dict(task='t_unregistered', mode='implementation')), set())
            self.assertNotIn('terminal', allowed(dict(task='t_stories', mode='implementation')))
            self.assertNotIn('planning_write', allowed(dict(task='t_stories', mode='review')))
            self.assertFalse(claim_allowed(self.db, 't_unregistered'))

    def test_parent_must_be_done_and_independently_approved(self):
        self.activate(); rev = self.freeze()
        self.c.planning.data['cards']['t_design']['parents'] = ['t_stories']
        for path in (self.board / 'planning.json', self.private / 'planning-config.json'):
            path.write_text(json.dumps(self.c.planning.data))
        self.activate('design')
        with self.assertRaises(PermissionError): self.op('planning_read')
        self.activate(run=2, review=True); self.op('validate', revision=rev); self.op('approve', revision=rev)
        self.db.execute("UPDATE tasks SET status='done' WHERE id='t_stories'"); self.db.commit()
        self.activate('design', 3)
        self.assertEqual(self.op('planning_read')['parents'][0]['revision'], rev)

    def test_invalid_documents_and_arbitrary_operations(self):
        self.activate()
        with self.assertRaises(ValueError): self.op('planning_write', content='placeholder')
        with self.assertRaises(PermissionError): self.op('terminal', command='id')
        self.assertEqual(self.op('planning_read')['brief'], self.brief)

    def test_checkpoint_adoption_patch_and_english_review(self):
        from planning_drafts import digest
        self.activate(); self.op('planning_write',content=self.content())
        old=self.content(); self.activate(run=3)
        result=self.op('planning_patch',expected_sha=digest(old),edits=[])
        self.assertTrue(result['ready_for_review'])
        self.assertTrue(self.op('freeze',reviewer='techlead')['revision'])
        self.activate(run=4,review=True)
        with self.assertRaises(PermissionError): self.op('planning_patch',expected_sha=digest(old),edits=[])
        from planning_flow import EN_SECTIONS
        self.c.planning.data['cards']['t_architecture']['language']='en'
        for path in (self.board/'planning.json',self.private/'planning-config.json'): path.write_text(json.dumps(self.c.planning.data))
        self.activate('architecture',5)
        with self.assertRaises(ValueError): self.op('planning_write',content=self.content())
        english=self.digest+'\n'+'\n'.join('## '+s+'\nConcrete technical decisions and acceptance criteria.' for s in EN_SECTIONS)
        self.op('planning_write',content=english)
        rev=self.op('freeze',reviewer='techlead')['revision']
        self.activate('architecture',6,True);self.op('validate',revision=rev)
        self.assertTrue(self.op('approve',revision=rev)['approved'])

    def test_pr_packet_frozen_with_report_and_approval_never_merges(self):
        packet=dict(pr=19,repository='codifydeep/truco-online',head_sha='a'*40,base_sha='b'*40,
                    diff='complete diff',files={'doc.md':'content'},
                    ci=dict(headSha='a'*40,conclusion='success'),trusted_guard_passed=True)
        raw=json.dumps(packet).encode()
        (self.private/'pr-review-packet.json').write_bytes(raw)
        card=self.c.planning.data['cards']['t_plan']
        card.update(scope='pr_review',packet_sha256=hashlib.sha256(raw).hexdigest(),head_sha='a'*40,base_sha='b'*40)
        for path in (self.board/'planning.json',self.private/'planning-config.json'):
            path.write_text(json.dumps(self.c.planning.data))
        self.activate('plan')
        self.assertEqual(self.op('planning_read')['pr_packet']['head_sha'],packet['head_sha'])
        for page in range(self.op('planning_read')['pr_packet']['page_count']): self.op('planning_read',page=page)
        with self.assertRaises(ValueError): self.op('planning_write',content=self.content())
        report=self.content('\n```json\n'+json.dumps(dict(head_sha='a'*40,base_sha='b'*40,decision='request_changes',
            findings=['The exported API criteria need a precise concurrency guarantee.']))+'\n```')
        self.op('planning_write',content=report)
        revision=self.op('freeze',reviewer='cto')['revision']
        self.activate('plan',2,True)
        with self.assertRaises(PermissionError): self.op('planning_write',content=report)
        with self.assertRaises(ValueError): self.op('validate',revision=revision)
        for page in range(self.op('planning_read')['pr_packet']['page_count']): self.op('planning_read',page=page)
        self.op('validate',revision=revision)
        receipt=self.op('approve',revision=revision)
        self.assertEqual(receipt['scope'],'pr_assessment')
        self.assertEqual(receipt['pr_assessment']['decision'],'request_changes')
        self.assertFalse(receipt['merge_allowed'])
        self.assertEqual((self.c.store.path('planning-test','t_plan',revision)/'files/PR-PACKET.json').read_bytes(),raw)
        (self.private/'pr-review-packet.json').write_text('{}')
        with self.assertRaises(PermissionError): self.op('approve',revision=revision)

    def test_correction_inputs_are_paginated_and_checked_in_review(self):
        self.c.planning.data['cards']['t_design']['correction_gate']=True
        for path in (self.board/'planning.json',self.private/'planning-config.json'):
            path.write_text(json.dumps(self.c.planning.data))
        self.activate('design')
        count=self.op('planning_read')['input_pages']
        body=''.join(self.op('planning_read',page=i)['content'] for i in range(count))
        self.assertEqual(json.loads(body)['brief'],self.brief)
        with self.assertRaises(ValueError): self.op('planning_read',page=count)
        with self.assertRaises(ValueError): self.op('planning_write',content=self.content('BRIEF-TRUCO-v0.1-R1-202616'))
        self.op('planning_write',content=self.content('BRIEF-TRUCO-v0.1-R1-20260916'))
        revision=self.op('freeze',reviewer='produto')['revision']
        self.activate('design',2,True)
        proof=self.op('validate',revision=revision)
        self.assertTrue(proof['correction_checks']['passed'])
        self.assertTrue(self.op('approve',revision=revision)['approved'])


if __name__ == '__main__': unittest.main()
