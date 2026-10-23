"""Private archive proof must match execution, source, counter and install."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import review_capacity_evidence as evidence
from install_quality_preview import save
from install_model_proxy_capacity import counter_receipt,private_digest
from qualify_quality_review_stop import sha
import test_quality_review_capacity_recovery as fixtures


class ReviewCapacityArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        f=fixtures.QualityReviewCapacityEvidenceTests();f.setUp();self.transport=copy.deepcopy(f.transport)
        self.request=f.request;self.operation=f.operation;self.namespace=f.namespace
        receipt=self.transport['installation'];self.install=receipt['install_operation']
        self.archive=self.root/'.local-test/backups'/('model-proxy-install-'+self.install)
        self.archive.mkdir(parents=True,mode=0o700);self.archive.parent.chmod(0o700);self.archive.parent.parent.chmod(0o700)
        before=dict(Id=receipt['previous_container'],Image=receipt['previous_image'],Config=dict(Env=[
            'MODEL_PROXY_MAX_CALLS=10000','MODEL_PROXY_COUNTER_PATH=/meter/calls.json']))
        save(self.archive/'before.json',before)
        program=b'MAX_BODY=512*1024\n';p=self.archive/'previous-model_proxy.py';p.write_bytes(program);p.chmod(0o600)
        receipt['previous_source_sha256']=sha(program)
        raw=b'{"calls":7}'
        for name in ('counter-before.json','counter-after.json'):
            p=self.archive/name;p.write_bytes(raw);p.chmod(0o600)
        receipt['counter']=counter_receipt(raw)
        self.logs=dict(container_id=receipt['previous_container'],stdout='2026-10-23T00:00:00Z '+json.dumps(self.transport['rejection']),stderr='')
        save(self.archive/'previous-proxy-logs.json',self.logs);receipt['previous_logs_sha256']=private_digest(self.archive/'previous-proxy-logs.json')
        self.state=dict(stage='installed_stopped',namespace=self.namespace,operation=self.install,
            maintenance_operation=self.operation,image=receipt['current_image'],
            qualification_id=receipt['qualification']['qualification_id'],receipt=receipt)
        save(self.archive/'state.json',self.state)

    def load(self):
        with patch.object(evidence,'ROOT',self.root),patch.object(evidence,'qualified',return_value=self.state['receipt']['qualification']):
            return evidence.load(self.namespace,self.install,self.operation,self.request)

    def test_exact_archived_rejection_and_unchanged_meter_are_required(self):
        self.assertEqual(self.load(),self.transport)
        self.assertFalse(self.load()['installation']['delivery_approval'])

    def test_unrelated_execution_or_modified_source_counter_or_logs_is_rejected(self):
        for name in ('previous-model_proxy.py','counter-after.json','previous-proxy-logs.json'):
            path=self.archive/name;original=path.read_bytes();path.write_bytes(b'{"calls":8}')
            with self.subTest(name=name),self.assertRaises(ValueError):self.load()
            path.write_bytes(original)
        self.transport['rejection']['execution_id']='a0000000-0000-4000-8000-000000000008'
        self.logs['stdout']='2026-10-23T00:00:00Z '+json.dumps(self.transport['rejection'])
        save(self.archive/'previous-proxy-logs.json',self.logs)
        self.state['receipt']['previous_logs_sha256']=private_digest(self.archive/'previous-proxy-logs.json')
        save(self.archive/'state.json',self.state)
        with self.assertRaises(ValueError):self.load()

    def test_ambiguous_rejections_or_later_success_cannot_be_used_as_capacity_failure(self):
        original=self.logs['stdout']
        success={**self.transport['rejection'],'status':200,'category':'upstream_response','started_at':124.}
        for suffix in (original,'2026-10-23T00:00:01Z '+json.dumps(success)):
            self.logs['stdout']=original+'\n'+suffix;save(self.archive/'previous-proxy-logs.json',self.logs)
            self.state['receipt']['previous_logs_sha256']=private_digest(self.archive/'previous-proxy-logs.json')
            save(self.archive/'state.json',self.state)
            with self.assertRaises(ValueError):self.load()


if __name__=='__main__':unittest.main()
