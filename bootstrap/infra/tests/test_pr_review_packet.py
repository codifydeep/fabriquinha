import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pr_review_packet import load, assessment, pages, manifest


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packet = dict(pr=19, repository='codifydeep/truco-online', head_sha='a'*40,
                           base_sha='b'*40, diff='diff', files={'doc.md':'content'},
                           ci=dict(headSha='a'*40, conclusion='success'), trusted_guard_passed=True)
        raw = json.dumps(self.packet).encode()
        (self.root/'pr-review-packet.json').write_bytes(raw)
        self.card = dict(scope='pr_review', packet_sha256=hashlib.sha256(raw).hexdigest(),
                         head_sha='a'*40, base_sha='b'*40)

    def report(self, **overrides):
        decision = dict(head_sha='a'*40, base_sha='b'*40, decision='approve', findings=[])
        decision.update(overrides)
        return '```json\n'+json.dumps(decision)+'\n```'

    def test_valid_packet_and_decision(self):
        self.assertEqual(load(self.root,self.card),self.packet)
        self.assertEqual(assessment(self.report(),self.packet)['decision'],'approve')

    def test_tamper_rejected(self):
        (self.root/'pr-review-packet.json').write_text('{}')
        with self.assertRaises(PermissionError): load(self.root,self.card)

    def test_content_addressed_packet_preserves_legacy_review(self):
        original = dict(self.card)
        new_packet = dict(self.packet, head_sha='c'*40, ci=dict(headSha='c'*40, conclusion='success'))
        raw = json.dumps(new_packet).encode()
        digest = hashlib.sha256(raw).hexdigest()
        directory = self.root/'pr-review-packets'; directory.mkdir()
        (directory/(digest+'.json')).write_bytes(raw)
        successor = dict(self.card, packet_storage='sha256', packet_sha256=digest, head_sha='c'*40)
        self.assertEqual(load(self.root,successor),new_packet)
        self.assertEqual(load(self.root,original),self.packet)
        (directory/(digest+'.json')).unlink()
        with self.assertRaises(FileNotFoundError): load(self.root,successor)

    def test_packet_storage_rejects_path_traversal(self):
        self.card.update(packet_storage='sha256', packet_sha256='../pr-review-packet')
        with self.assertRaises(ValueError): load(self.root,self.card)

    def test_stale_identity_rejected(self):
        self.card['base_sha']='c'*40
        with self.assertRaises(PermissionError): load(self.root,self.card)
        with self.assertRaises(ValueError): assessment(self.report(head_sha='c'*40),self.packet)

    def test_foundation_requires_explicit_registered_pr_identity(self):
        packet=dict(self.packet,pr=14)
        raw=json.dumps(packet).encode()
        (self.root/'pr-review-packet.json').write_bytes(raw)
        self.card['packet_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaises(PermissionError): load(self.root,self.card)
        self.card['pr_number']=14
        self.assertEqual(load(self.root,self.card)['pr'],14)
        self.card['pr_number']=20
        with self.assertRaises(PermissionError): load(self.root,self.card)

    def test_explicit_changes_valid_and_need_findings(self):
        with self.assertRaises(ValueError): assessment(self.report(decision='request_changes'),self.packet)
        result=assessment(self.report(decision='request_changes',findings=['Correct the documented API contract mismatch.']),self.packet)
        self.assertEqual(result['decision'],'request_changes')

    def test_no_fabricated_merge_or_ambiguous_decisions(self):
        with self.assertRaises(ValueError): assessment(self.report(decision='merged'),self.packet)
        with self.assertRaises(ValueError): assessment(self.report()+self.report(),self.packet)

    def test_paginated_payload_is_complete_and_bounded(self):
        self.packet['diff']='line\n'*50000
        chunks=pages(self.packet)
        self.assertTrue(all(len(c)<=8000 for c in chunks))
        self.assertEqual(json.loads(''.join(chunks)),self.packet)
        self.assertEqual(manifest(self.packet)['page_count'],len(chunks))


if __name__=='__main__': unittest.main()
