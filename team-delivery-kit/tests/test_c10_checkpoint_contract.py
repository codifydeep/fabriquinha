import copy
import unittest
from broker import c10_checkpoint_contract as gate, suite_failure


class C10CheckpointContractTests(unittest.TestCase):
    def setUp(self):
        lines=[b'// immutable\n']*679
        for i in gate.QUERY_LINES:lines[i-1]=b'    resolveNewest([{ id: 3, title: "sentinel" }]);\n'
        lines[533:536]=[b'// C10STATUS - placeholder checkpoint\n',b'return flush().then(function () {\n',b'});\n']
        self.seed=b''.join(lines);self.query=gate.query_candidate(self.seed)
        self.scope=dict(gate.verify_bytes('QUERY',self.seed,self.query),manifest_sha256='a'*64)
        self.state={'author_task':'query-author','snapshot':{'volume':'query'},
            'validation':{'test_sha256':gate.sha(self.query),'manifest_sha256':'a'*64},
            'c10_checkpoints':{'schema':gate.SCHEMA,'phase':'QUERY','scope_receipt':self.scope,
                'seed':{'validation':{'test_sha256':gate.sha(self.seed)}}}}
        self.output=('ERROR: '+gate.C10+' (tests.test_incremental_u3.DriverTests)\n'
            "KeyError: 'status_genA_urls'\nRan 259 tests in 1.0s\nFAILED (errors=1)\n")

    def partial(self,output=None,state=None):
        output=self.output if output is None else output;state=state or self.state
        failure=suite_failure.evidence(1,output,state['author_task'],state['snapshot']['volume'])
        return gate.partial_receipt(state,failure,output)

    def test_query_all_four_only_and_frozen_status(self):
        self.assertTrue(gate.verify_bytes('QUERY',self.seed,self.query)['scope_verified'])
        for candidate in (self.seed,self.query.replace(b'// immutable',b'// change',1),
                self.query.replace(b'placeholder checkpoint',b'changed checkpoint'),
                self.query.replace(b'({items:[',b'([',1),self.query.replace(b'sentinel',b'fake',1)):
            with self.assertRaises(ValueError):gate.verify_bytes('QUERY',self.seed,candidate)

    def test_query_permits_only_whitespace_inside_inserted_envelope(self):
        spaced=self.query.replace(b'{items:',b'{ items: ').replace(b']});',b'] });')
        self.assertTrue(gate.verify_bytes('QUERY',self.seed,spaced)['scope_verified'])
        for changed in (spaced.replace(b'items:',b'wrong:',1),spaced.replace(b'sentinel',b'forged',1),
                spaced.replace(b'    resolveNewest',b'   resolveNewest',1),
                spaced.replace(b'] });',b'], extra: true });',1),spaced.replace(b'{ items:',b'{\nitems:',1)):
            with self.assertRaises(ValueError):gate.verify_bytes('QUERY',self.seed,changed)
        lines=spaced.splitlines(keepends=True)
        status=b''.join(lines[:533]+[b'// actual future STATUS driver\n']+lines[536:])
        self.assertTrue(gate.verify_bytes('STATUS',spaced,status)['scope_verified'])

    def test_status_preserves_query_closure_and_tests(self):
        lines=self.query.splitlines(keepends=True)
        candidate=b''.join(lines[:533]+[b'// actual future STATUS driver\n']+lines[536:])
        self.assertTrue(gate.verify_bytes('STATUS',self.query,candidate)['scope_verified'])
        for source,target in ((self.seed,candidate),(self.query,self.query),
                (self.query,candidate.replace(b'sentinel',b'other',1)),
                (self.query,candidate.replace(b'// immutable',b'changed',1))):
            with self.assertRaises(ValueError):gate.verify_bytes('STATUS',source,target)

    def test_partial_is_not_green_or_authority(self):
        proof=self.partial()
        self.assertEqual(proof['result'],'PARTIAL');self.assertFalse(proof['green'])
        self.assertFalse(proof['delivery_approval']);self.assertFalse(proof['author_scope_authorized'])

    def test_actual_runner_diagnostic_metadata_preserved_without_relaxing_core(self):
        failure=suite_failure.evidence(1,self.output,self.state['author_task'],self.state['snapshot']['volume'])
        failure['diagnostic_read_files']=['app/static/app.js','app/static/index.html','tests/test_incremental_u3.py']
        proof=gate.partial_receipt(self.state,failure,self.output)
        self.assertEqual(proof['full_suite_failure'],failure)
        for changed in (dict(failure,tests_executed=258),dict(failure,unrecognized=True),
                dict(failure,diagnostic_read_files=['secret']),dict(failure,diagnostic_read_files=[])):
            with self.assertRaises(ValueError):gate.partial_receipt(self.state,changed,self.output)

    def test_only_exact_single_expected_error_full_count_and_no_skips(self):
        for output in (self.output.replace('259','258'),self.output.replace('ERROR:','FAIL:'),
                self.output.replace('status_genA_urls','other'),self.output.replace('errors=1','errors=2'),
                self.output.replace('errors=1','errors=1, skipped=1'),self.output+"KeyError: 'status_genA_urls'\n",
                self.output+'Ran 259 tests in 1.0s\n',self.output.replace(gate.C10,'test_c09_regression'),
                self.output+'AssertionError: failed\n'):
            with self.assertRaises(ValueError):self.partial(output)

    def test_stale_scope_or_raw_report_fails_closed(self):
        for field,value in (('test_sha256','b'*64),('manifest_sha256','b'*64),('scope_verified',False)):
            state=copy.deepcopy(self.state);state['c10_checkpoints']['scope_receipt'][field]=value
            with self.assertRaises(ValueError):self.partial(state=state)
        failure=suite_failure.evidence(1,self.output,'wrong-author','query')
        with self.assertRaises(ValueError):gate.partial_receipt(self.state,failure,self.output)

    def test_status_green_retains_exact_partial_lineage_and_requires_review(self):
        partial=self.partial();state=copy.deepcopy(self.state)
        state.update(author_task='status-author',snapshot={'volume':'status'},
            validation={'test_sha256':'b'*64,'manifest_sha256':'c'*64})
        state['c10_checkpoints'].update(phase='STATUS',query_receipt=partial,
            seed={'task_id':partial['source_task'],'snapshot':partial['snapshot'],'validation':partial['validation']},
            scope_receipt={'schema':gate.SCHEMA,'phase':'STATUS','scope_verified':True,'delivery_approval':False,
                'seed_test_sha256':partial['validation']['test_sha256'],'test_sha256':'b'*64,'manifest_sha256':'c'*64})
        green={'source_task':'status-author','volume':'status','manifest_sha256':'c'*64,'test_sha256':'b'*64,
            'tests':259,'exit_code':0,'network':'none','snapshot_mount':'readonly',
            'executed_by':'controller_maintenance_full_suite','delivery_approval':False}
        output='Ran 259 tests in 1.0s\nOK\n';green['output_sha256']=gate.sha(output.encode())
        proof=gate.final_receipt(state,green,output)
        self.assertEqual(proof['result'],'AWAITING_INDEPENDENT_REVIEW');self.assertFalse(proof['delivery_approval'])
        for field,value in (('tests',258),('source_task','stale'),('test_sha256','a'*64),('exit_code',1),
                ('network','host'),('delivery_approval',True)):
            with self.assertRaises(ValueError):gate.final_receipt(state,dict(green,**{field:value}),output)
        for invalid in ('Ran 259 tests in 1.0s\nOK (skipped=1)\n','Ran 258 tests\nOK\n',output+'ERROR: test_failure (tests.Test)\n'):
            with self.assertRaises(ValueError):gate.final_receipt(state,dict(green,output_sha256=gate.sha(invalid.encode())),invalid)
        state['suite_receipt']=green;state['c10_checkpoints']['final_receipt']=proof
        gate.require_review_ready(state)
        state['suite_receipt']=dict(green,test_sha256='stale')
        with self.assertRaises(ValueError):gate.require_review_ready(state)
        state['c10_checkpoints']['query_receipt']['green']=True
        with self.assertRaises(ValueError):gate.final_receipt(state,green,output)
