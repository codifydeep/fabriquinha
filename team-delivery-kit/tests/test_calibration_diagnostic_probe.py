import unittest
from calibration_diagnostic_probe import build
from calibration_response_contract import capsule, context


class DiagnosticProbeTests(unittest.TestCase):
    def setUp(self):
        self.experiment='11111111-1111-4111-8111-111111111111'
        self.task='22222222-2222-4222-8222-222222222222'
        self.path='/evidence/candidate/tests/test_one.py'
        self.note=capsule(context('bundle',[self.path],'a'*64))
        self.reads=[dict(type='tool_use',tool='read_file',call_id='read1',input={'path':self.path}),
            dict(type='tool_result',tool='read_file',call_id='read1',output=
                'Read '+self.path+' — 1 total lines\n\n```\n1|pass\n```')]

    def test_preserved_inputs_are_not_native_proof_or_permission(self):
        body,receipt=build(self.note,self.reads,'model',self.experiment,self.task)
        self.assertEqual(len(body['messages']),4)
        for field in ('native_read_evidence','execution_authorized','delivery_approval',
                      'workflow_transition','tool_execution_allowed'):
            self.assertIs(receipt[field],False)

    def test_missing_foreign_or_duplicate_read_is_rejected(self):
        for reads in ([],self.reads*2,[self.reads[0],dict(self.reads[1],call_id='foreign')]):
            with self.assertRaises(ValueError):build(self.note,reads,'model',self.experiment,self.task)

    def test_cannot_impersonate_task_or_switch_phase(self):
        with self.assertRaises(ValueError):build(self.note,self.reads,'model',self.task,self.task)
        note=capsule(context('review',[self.path],'a'*64,'b'*64,'c'*64))
        with self.assertRaises(ValueError):build(note,self.reads,'model',self.experiment,self.task)
