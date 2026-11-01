import json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from fabriquinha.artifacts import Store,digest
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.authoring_recovery import eligible
from test_delivery_core import configuration

class AuthoringAdmission(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name));self.project=Project.parse({**configuration(),'technical_roles':{'lead':'lead','cto':'cto'}})
        self.body=dict(kind='tests',release='r',package='second',criteria=['PLAY'])
        self.source=Run('source',2,'qa','tests',False,'qa','r',digest(self.body))
        self.cto=Run('diagnosis',3,'cto','diagnostic',False,'cto','r','context')
        self.baseline='a'*64
    def check(self,*,review=False,kind='tests',snapshot=None,failed=False,actor='cto',effects=None,body=None):
        snapshot=snapshot or self.baseline;source=replace(self.source,kind=kind,reviewing=review)
        incident=self.store.record('incident',source.binding(),dict(project=self.project.fingerprint(),
            source='source',source_run=2,source_state='triage',resume_allowed=False,
            controller_effects=[] if effects is None else effects,snapshot=snapshot,
            failure='activity ended without a controller-validated native handoff; SDK status '+json.dumps(dict(code='missing_terminal_operation',failed=failed,api_calls=11))))
        binding=replace(self.cto,actor=actor).binding()
        experiment=self.store.record('diagnostic_experiment',binding,dict(project=self.project.fingerprint(),incident=incident,snapshot=snapshot))
        decision=self.store.record('diagnostic_decision',binding,dict(project=self.project.fingerprint(),incident=incident,experiment=experiment,action='hold',delivery_approval=False))
        return eligible(self.project,self.store,incident,decision,body or self.body,self.baseline,snapshot)
    def test_empty_authoring_is_eligible_not_delivery_approval(self):
        self.assertEqual(self.check()['binding']['task'],'source')
    def test_other_phases_and_errors_refused(self):
        for kwargs in ({'review':True},{'kind':'implementation'},{'failed':True},{'actor':'lead'},{'effects':['pending']}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.check(**kwargs)
    def test_modified_candidate_or_contract_refused(self):
        for kwargs in ({'snapshot':'b'*64},{'body':{**self.body,'criteria':['OTHER']}},{'body':{**self.body,'authoring_repair':'prior'}}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.check(**kwargs)
