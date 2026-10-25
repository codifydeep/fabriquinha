"""Status transport is simulated; CI still computes from real Git snapshots."""
import json
from unittest.mock import Mock
import unittest

import test_local_ci as fixtures
from fabriquinha.config import Project
from fabriquinha.effects import EffectBlocked,Pending
from fabriquinha.publication import GitHub,LocalStatus
from test_delivery_core import configuration


class StatusTransport:
    def __init__(self):
        self.values={};self.calls=0;self.lose=False
    def local_status(self,head):return self.values.get(head)
    def publish_local_status(self,head,state,description):
        self.calls+=1
        self.values[head]=dict(id=self.calls,state=state,description=description,
            context='fabriquinha-local-ci',creator=dict(login='fixture'))
        if self.lose:raise TimeoutError('accepted remotely; ACK lost')
        return self.values[head]


class StatusFlow(unittest.TestCase):
    propose=fixtures.LocalCIBoundaries.propose
    execute=fixtures.LocalCIBoundaries.execute
    def setUp(self):
        fixtures.LocalCIBoundaries.setUp(self)
        self.project=Project.parse({**configuration(),'local_ci':dict(context='fabriquinha-local-ci',publisher='fixture')})
        self.repo.project=self.project;self.ci.project=self.project
        self.github=StatusTransport()
        self.status=LocalStatus(self.project,self.store,self.repo,self.github,self.runner)

    def test_real_computation_binds_remote_status_and_reuses_completed_effect(self):
        head=self.propose();first=self.status.publish(head,self.base,stage='proposal')
        second=self.status.publish(head,self.base,stage='proposal')
        self.assertEqual(first,second);self.assertEqual(self.github.calls,1)
        proof=self.store.receipt(first['receipt'],kind='ci_validation')
        self.assertEqual(proof['payload']['head'],head);self.assertFalse(proof['payload']['delivery_approval'])

    def test_lost_ack_observes_without_a_second_post_after_reconstruction(self):
        head=self.propose();self.github.lose=True
        with self.assertRaises(Pending):self.status.publish(head,self.base,stage='proposal')
        resumed=LocalStatus(self.project,self.store,self.repo,self.github,self.runner)
        resumed.publish(head,self.base,stage='proposal');self.assertEqual(self.github.calls,1)

    def test_completed_journal_never_hides_a_foreign_or_overwritten_status(self):
        head=self.propose();self.status.publish(head,self.base,stage='proposal')
        original=dict(self.github.values[head])
        for update in (dict(state='failure'),dict(description='another proof'),dict(creator={'login':'someone-else'})):
            self.github.values[head]={**original,**update}
            with self.subTest(update=update),self.assertRaises(EffectBlocked):
                self.status.publish(head,self.base,stage='proposal')
        self.assertEqual(self.github.calls,1)

    def test_failure_is_published_but_never_accepted(self):
        head=self.propose();self.report['failures']=[dict(case=self.report['cases'][0])];self.exit=1
        with self.assertRaisesRegex(EffectBlocked,'assertions failed'):self.status.publish(head,self.base,stage='proposal')
        self.assertEqual(self.github.values[head]['state'],'failure')

    def test_invalid_report_never_publishes_success(self):
        head=self.propose();self.report['skips']=['ignored']
        with self.assertRaises(ValueError):self.status.publish(head,self.base,stage='proposal')
        self.assertEqual(self.github.calls,0)

    def test_missing_or_foreign_durable_receipt_cannot_be_replaced_with_green_text(self):
        head=self.propose()
        with self.assertRaises(EffectBlocked):self.status.existing(head,self.base,stage='proposal')
        self.status.publish(head,self.base,stage='proposal')
        self.github.values.pop(head)
        with self.assertRaises(Pending):self.status.existing(head,self.base,stage='proposal')
        self.assertEqual(self.github.calls,1)

    def test_pause_fence_before_send_never_posts(self):
        head=self.propose();ensure=Mock(side_effect=EffectBlocked('paused'))
        with self.assertRaises(EffectBlocked):self.status.publish(head,self.base,stage='proposal',ensure=ensure)
        self.assertEqual(self.github.calls,0)


class FixedStatusAPI(unittest.TestCase):
    def setUp(self):
        self.project=Project.parse({**configuration(),'qualification':False,
            'local_ci':dict(context='fabriquinha-local-ci',publisher='fixture')})
        self.github=GitHub(self.project,'devops');self.github.cli=Mock()
        self.head='a'*40;self.description='Fabriquinha receipt '+'b'*64

    def test_account_and_fixed_endpoint_are_verified_before_post(self):
        self.github.cli.side_effect=[json.dumps({'login':'fixture'}),'{}','[]']
        self.github.publish_local_status(self.head,'success',self.description)
        posted=self.github.cli.call_args_list[1]
        self.assertEqual(posted.args,('api','--method','POST','repos/example/product/statuses/'+self.head,'--input','-'))
        self.assertEqual(json.loads(posted.kwargs['data']),dict(state='success',description=self.description,context='fabriquinha-local-ci'))

    def test_wrong_account_or_invalid_provenance_never_posts(self):
        self.github.cli.return_value=json.dumps(dict(login='other'))
        with self.assertRaises(EffectBlocked):self.github.publish_local_status(self.head,'success',self.description)
        self.assertEqual(self.github.cli.call_count,1)
        for state,description in [('pending',self.description),('success','passed')]:
            with self.assertRaises(ValueError):self.github.publish_local_status(self.head,state,description)
        self.assertEqual(self.github.cli.call_count,1)

    def test_paginated_inventory_uses_latest_id_and_fails_closed_when_incomplete(self):
        row=dict(id=1,context='fabriquinha-local-ci')
        self.github.cli.side_effect=[json.dumps([row]*100),json.dumps([{**row,'id':2}])]
        self.assertEqual(self.github.local_status(self.head)['id'],2)
        self.github.cli.side_effect=None;self.github.cli.return_value=json.dumps([row]*100)
        with self.assertRaisesRegex(ValueError,'incomplete bounded'):self.github.local_status(self.head)

    def test_policy_is_opt_in_immutable_and_never_changes_main(self):
        raw={**configuration(),'local_ci':dict(self.project.local_ci)}
        parsed=Project.parse(raw);raw['local_ci']['publisher']='other'
        self.assertEqual(parsed.local_ci['publisher'],'fixture')
        with self.assertRaises(TypeError):parsed.local_ci['publisher']='other'
        for update in (dict(branch='main'),dict(branch='master'),dict(local_ci={'context':'ci','publisher':'fixture'})):
            with self.assertRaises(ValueError):Project.parse({**raw,**update})


if __name__=='__main__':unittest.main()
