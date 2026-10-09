import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from portable_qa_protocol_recovery import qualify,recover,digest
from release_eval import save_receipt


class ProtocolRecoveryTests(unittest.TestCase):
    def test_real_cto_recovery_record_preserves_old_card_and_dispatches_once(self):
        from portable_qa_cto import record
        class Board:
            def __init__(self):
                self.cards={'diagnosis':{'id':'diagnosis','metadata':{}}}
                self.runs={};self.starts=0
            def __call__(self,command,*args):
                if command=='search':return {'issues':list(self.cards.values())}
                if command=='create':
                    identifier='card-'+str(len(self.cards))
                    card={'id':identifier,'title':args[args.index('--title')+1],
                        'parent_issue_id':args[args.index('--parent')+1],'status':'blocked',
                        'metadata':{},'assignee_id':None}
                    self.cards[identifier]=card;return card
                if command=='get':return self.cards[args[0]]
                if command=='metadata':
                    metadata=self.cards[args[1]]['metadata']
                    if args[0]=='set':metadata[args[args.index('--key')+1]]=args[args.index('--value')+1]
                    return metadata
                if command=='runs':return self.runs.get(args[0],[])
                card=self.cards[args[0]]
                if command in ('assign','status'):
                    assert '--no-start' in args
                    if command=='assign':card['assignee_id']=args[args.index('--to-id')+1]
                    else:card['status']=args[1]
                    return card
                if command=='rerun':
                    self.starts+=1;self.runs[args[0]]=[{'id':'task-'+str(self.starts),
                        'agent_id':'cto','status':'running'}];return self.runs[args[0]][0]
                raise AssertionError(command)
        with tempfile.TemporaryDirectory() as folder,patch('portable_qa_evidence.bind'):
            incident={'phase':'browser','key':'12345678abcdefab','source_sha':'a'*40,
                'child_issue_id':'diagnosis','category':'post-deploy browser QA fixture failed'}
            contract={'editable_files':['app.py'],'test_files':[],'test_roots':['tests']}
            board=Board()
            args=dict(incident=incident,parent_contract=contract,cto_id='cto',reason='failed')
            original=record(folder,board,**args,budget_ready=True)
            board.runs[original['child_issue_id']][0]['status']='failed'
            original=record(folder,board,**args,budget_ready=False)
            old_path=Path(folder)/'qa-cto-escalations'/(incident['key']+'.json')
            old_bytes=old_path.read_bytes()
            _,_,failed=self.fixture();failed['task_id']='task-1';failed['read_proof']['task_id']='task-1'
            key,value=qualify(folder,inspect=lambda:('proxy',self.identity()),execute=self.probe)
            result=recover(folder,board,incident=incident,original=original,parent_contract=contract,
                budget_ready=True,observe=lambda *_:failed,qualification=lambda _: (key,value))
            again=recover(folder,board,incident=incident,original=original,parent_contract=contract,
                budget_ready=True,observe=lambda *_:failed,inspect=lambda:('proxy',self.identity()),
                qualification=lambda _:self.fail('no second fixture'))
            self.assertEqual(result,again)
            self.assertNotEqual(result['child_issue_id'],original['child_issue_id'])
            self.assertEqual(board.starts,2)
            self.assertEqual(old_path.read_bytes(),old_bytes)
            self.assertEqual(board.runs[original['child_issue_id']][0]['status'],'failed')
            metadata=board.cards['diagnosis']['metadata']
            self.assertEqual(metadata['qa_cto_issue_id'],original['child_issue_id'])
            self.assertEqual(metadata['qa_cto_protocol_issue_id'],result['child_issue_id'])

    def identity(self):
        return {'image':'sha256:'+'a'*64,'modules':{'parser':'b'*64},'fixture_sha256':'c'*64}

    def probe(self):
        return {'kind':'protocol_fixture_not_delivery_evidence','status':200,
            'local_validation':'passed','json_valid':True,'done_markers':1,'call':9,'sha256':'d'*64}

    def test_probe_is_counted_once_and_cache_does_not_authorize_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            inspect=lambda:('owned-proxy',self.identity())
            def execute():calls.append(True);return self.probe()
            first=qualify(folder,inspect=inspect,execute=execute)
            second=qualify(folder,inspect=inspect,execute=lambda:self.fail('no repeat'))
            self.assertEqual(first,second)
            self.assertEqual(len(calls),1)
            self.assertIs(first[1]['delivery_approval'],False)

    def test_lost_or_rejected_probe_is_never_blindly_repeated(self):
        for result in (None,{**self.probe(),'local_validation':'rejected'}):
            with self.subTest(result=result),tempfile.TemporaryDirectory() as folder:
                def execute():
                    if result is None:raise TimeoutError('observation lost')
                    return result
                with self.assertRaises((ValueError,TimeoutError)):
                    qualify(folder,inspect=lambda:('proxy',self.identity()),execute=execute)
                with self.assertRaisesRegex(ValueError,'no automatic replay'):
                    qualify(folder,inspect=lambda:('proxy',self.identity()),execute=lambda:self.fail('no replay'))

    def test_installation_drift_leaves_unknown_intent_not_qualification(self):
        with tempfile.TemporaryDirectory() as folder:
            identities=iter([self.identity(),{**self.identity(),'image':'sha256:'+'f'*64}])
            with self.assertRaisesRegex(ValueError,'installation changed'):
                qualify(folder,inspect=lambda:('proxy',next(identities)),execute=self.probe)
            receipt=json.loads(next((Path(folder)/'qa-protocol-qualifications').glob('*.json')).read_text())
            self.assertEqual(receipt['stage'],'probe_intent')

    def fixture(self):
        incident={'phase':'browser','key':'12345678abcdefab','source_sha':'a'*40}
        original={'dispatch':'cto_failed','child_issue_id':'failed-card','cto_id':'cto','reason':'failed'}
        failed={'task_id':'failed-task','closed_planning':True,'source_sha':incident['source_sha'],
                'delivery_approval':False,'read_proof':{'status':'read_evidence_verified','task_id':'failed-task'}}
        return incident,original,failed

    def test_one_recovery_reuses_proof_and_preserves_old_failed_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            incident,original,failed=self.fixture()
            key,value=qualify(folder,inspect=lambda:('proxy',self.identity()),execute=self.probe)
            def record(*args,**kwargs):
                proof=kwargs['protocol_recovery']
                save_receipt(Path(folder)/'qa-cto-protocol-recoveries'/(incident['key']+'.json'),
                             {'protocol_recovery':proof,'child_issue_id':'new-card'})
                return {'child_issue_id':'new-card','dispatch':'cto_started'}
            with patch('portable_qa_cto.record',side_effect=record):
                result=recover(folder,None,incident=incident,original=original,parent_contract={},
                    budget_ready=True,observe=lambda *_:failed,qualification=lambda _: (key,value))
                again=recover(folder,None,incident=incident,original=original,parent_contract={},
                    budget_ready=True,observe=lambda *_:failed,inspect=lambda:('proxy',self.identity()),
                    qualification=lambda _:self.fail('never qualify or probe again'))
            self.assertEqual(result,again)
            self.assertEqual(original['child_issue_id'],'failed-card')
            self.assertEqual(original['dispatch'],'cto_failed')

    def test_bad_failure_proof_or_budget_pause_cannot_probe_or_start(self):
        incident,original,failed=self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(recover(folder,None,incident=incident,original=original,
                parent_contract={},budget_ready=False,observe=lambda *_:self.fail('no observation')))
            for invalid in ({**failed,'delivery_approval':True},{**failed,'closed_planning':False},
                            {**failed,'read_proof':{}},{**failed,'source_sha':'other'}):
                with self.assertRaisesRegex(ValueError,'failed diagnostic proof'):
                    recover(folder,None,incident=incident,original=original,parent_contract={},
                        budget_ready=True,observe=lambda *_:invalid,
                        qualification=lambda _:self.fail('no model call or dispatch'))
