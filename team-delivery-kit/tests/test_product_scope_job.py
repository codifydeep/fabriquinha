import hashlib
import json
import unittest
from unittest.mock import Mock,patch
import test_product_scope_execution as fixtures
from broker import product_scope_ledger as ledger
from broker import product_scope_revision as policy
from broker import product_scope_job as job


class ProductScopeJobTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.ProductScopeExecutionTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for field in ('b','fx','base','key','context','proposal','original','task'):
            if hasattr(fixture,field):setattr(self,field,getattr(fixture,field))
        self.b.PREFIX='delivery-kit-test';self.b.OWNER='owner'
        self.base=dict(volume='base-volume',base_sha='a'*40,manifest_sha256='b'*64)
        self.b.issue_base=Mock(return_value=self.base)
        self.volume=None
        def docker(method,path,payload=None):
            if method=='GET':return self.volume
            self.volume=dict(Name=payload['Name'],Labels=payload['Labels']);return self.volume
        self.b.docker=Mock(side_effect=docker)
        review=dict(operation='review_product_scope_revision_v1',proposal_sha256=policy.digest(self.proposal),
            decision='approve',reason='Necessary code only.')
        cto=self.task('cto','cto-task','cto-wake',self.proposal)
        lead=self.task('lead','lead-task','lead-wake',review)
        self.fx.task.side_effect=lambda task,actor:cto if task=='cto-task' else lead
        self.fx.read_hashes.return_value=self.context['eligible_code_sha256']
        with self.b.db() as con:
            ledger.record_proposal(con,self.key,self.proposal,cto)
            state=ledger.record_review(con,self.key,review,lead,self.context['eligible_code_sha256'])
            self.state=ledger.save_transition(con,state,dict(state,dispatch={
                'proposal':{'wakeup_id':'cto-wake'},'review':{'wakeup_id':'lead-wake'}}))
        expected=policy.candidate_contract(self.original,self.context,self.proposal)
        self.receipt=dict(operation='materialized_product_scope_plan_v1',issue_id='issue',source_task='source',
            proposal_sha256=policy.digest(self.proposal),review_task='lead-task',base_sha=self.base['base_sha'],
            original_base_manifest_sha256=self.base['manifest_sha256'],manifest_sha256='f'*64,
            original_contract_sha256=self.context['contract_sha256'],contract_sha256=policy.digest(expected),
            contract=expected,frozen_test_sha256=self.context['frozen_test_sha256'],delivery_approval=False,
            write_grant_issued=False,historical_red_recreated=False)
        output=json.dumps(self.receipt)
        self.result=dict(exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                         validation_job_key='e'*64,approval=False)

    def test_success_is_durable_and_never_installs_or_unblocks_author(self):
        with patch.object(job.validation_job,'run',return_value=self.result) as run:
            state=job.tick(self.b,self.key,self.fx)
            self.assertEqual(state['materialization']['stage'],'complete')
            self.assertTrue(state['author_blocked']);self.assertEqual(state['stage'],'plan_approved')
            self.assertEqual(job.tick(self.b,self.key,self.fx),state)
            run.assert_called_once()
            payload=run.call_args.args[3]
            self.assertEqual(payload['Image'],job.IMAGE)
            self.assertEqual(payload['HostConfig']['Mounts'][0]['ReadOnly'],True)
            self.assertEqual(payload['HostConfig']['NetworkMode'],'none')
            self.assertNotIn('installed_contract',state)

    def recovered_review(self):
        parent=dict(self.state,key='failed-parent',stage='blocked',
                    incident=dict(category='invalid_scope_review',task_id='failed-review'))
        parent.pop('review');parent.pop('review_task');parent.pop('qualification')
        with self.b.db() as con:
            con.execute('INSERT INTO product_scope_plans VALUES (?,?)',(parent['key'],ledger.encoded(parent)))
        state=dict(self.state,dispatch={'review':self.state['dispatch']['review']},
            mount_recovery=dict(previous_plan=parent['key'],proof=dict(
                operation='qualified_scope_mount_recovery_v1',original_plan_sha256=policy.digest(parent),
                proposal_sha256=self.state['proposal_sha256'],failed_task='failed-review',
                delivery_approval=False,write_grant_issued=False)))
        self.fx.b=self.b
        return state,parent

    def test_recovered_review_authenticates_original_proposal_without_replaying_cto(self):
        state,parent=self.recovered_review()
        job.reauthenticate(state,self.fx)
        self.assertEqual(job.proposal_wakeup(state,self.fx),'cto-wake')
        self.fx.wake.assert_not_called()
        with self.b.db() as con:self.assertEqual(ledger.load(con,parent['key']),parent)

    def test_reused_proposal_rejects_changed_parent_or_authorization(self):
        state,parent=self.recovered_review()
        for field,value in (('original_plan_sha256','0'*64),('proposal_sha256','0'*64),
                            ('delivery_approval',True),('failed_task','other')):
            with self.subTest(field=field):
                proof=dict(state['mount_recovery']['proof'],**{field:value})
                changed=dict(state,mount_recovery=dict(state['mount_recovery'],proof=proof))
                with self.assertRaises(ValueError):job.reauthenticate(changed,self.fx)
        changed=dict(state,proposal_task=dict(state['proposal_task'],id='other'))
        with self.assertRaises(ValueError):job.reauthenticate(changed,self.fx)

    def test_recovery_never_inherits_old_review_wakeup(self):
        state,parent=self.recovered_review();state['dispatch']={}
        with self.assertRaises(ValueError):job.reauthenticate(state,self.fx)

    def held_lineage(self):
        state,parent=self.recovered_review()
        held=dict(stage='blocked',incident=dict(category='scope_materialization_rejected',automatic_retry=False))
        state=dict(state,materialization=held)
        config=dict(issue_id=state['context']['issue_id'],contract_sha256=state['context']['contract_sha256'],enabled=True)
        run=dict(stage='blocked',plan_key=self.key,source_task=state['context']['source_task'],
                 delivery_approval=False,incident=dict(category='scope_pipeline_precondition_rejected',phase='scope_plan'))
        with self.b.db() as con:
            ledger.save_transition(con,self.state,state)
            con.execute('CREATE TABLE product_scope_runs(issue_id TEXT,config TEXT,state TEXT)')
            con.execute('INSERT INTO product_scope_runs VALUES (?,?,?)',(config['issue_id'],ledger.encoded(config),ledger.encoded(run)))
            con.execute('CREATE TABLE validation_jobs(identity TEXT)')
        return config,run,state

    def test_pre_effect_lineage_recovery_reauthenticates_and_preserves_decisions(self):
        config,run,state=self.held_lineage()
        after=job.recover_proposal_lineage(self.b,config,run,self.fx)
        self.assertEqual(after['stage'],'scope_plan');self.assertFalse(after['delivery_approval'])
        with self.b.db() as con:current=ledger.load(con,self.key)
        self.assertNotIn('materialization',current)
        for field in ('proposal','proposal_task','review','review_task','qualification'):
            self.assertEqual(current[field],state[field])
        self.assertEqual(current['reauthentication_recovery']['previous_materialization'],state['materialization'])
        self.fx.wake.assert_not_called()
        self.assertEqual(self.b.docker.call_args.args[0],'GET')

    def test_pre_effect_recovery_rejects_any_existing_job_or_volume(self):
        config,run,state=self.held_lineage()
        with self.b.db() as con:
            con.execute('INSERT INTO validation_jobs VALUES (?)',(json.dumps(dict(task=state['review_task']['id'],kind='scope_materialize')),))
        with self.assertRaises(ValueError):job.recover_proposal_lineage(self.b,config,run,self.fx)
        self.b.docker.assert_not_called()
        with self.b.db() as con:con.execute('DELETE FROM validation_jobs')
        self.volume=dict(Name='already-created')
        with self.assertRaises(ValueError):job.recover_proposal_lineage(self.b,config,run,self.fx)
        with self.b.db() as con:self.assertEqual(ledger.load(con,self.key),state)

    def test_richer_materialization_intent_or_unrelated_failure_is_not_reset(self):
        config,run,state=self.held_lineage()
        with self.b.db() as con:
            ledger.save_transition(con,state,dict(state,materialization=dict(state['materialization'],volume='existing-intent')))
        self.assertEqual(job.recover_proposal_lineage(self.b,config,run,self.fx),run)
        self.fx.verify_binding.assert_not_called();self.b.docker.assert_not_called()

    def test_pending_job_reuses_same_payload_and_volume(self):
        with patch.object(job.validation_job,'run',side_effect=[job.validation_job.Pending('live'),self.result]) as run:
            with self.assertRaises(job.validation_job.Pending):job.tick(self.b,self.key,self.fx)
            job.tick(self.b,self.key,self.fx)
            self.assertEqual(run.call_args_list[0],run.call_args_list[1])
            self.assertEqual(sum(c.args[0]=='POST' for c in self.b.docker.call_args_list),1)

    def test_unknown_volume_create_ack_is_observed_without_duplicate_post(self):
        original=self.b.docker.side_effect
        def uncertain(method,path,payload=None):
            result=original(method,path,payload)
            if method=='POST':raise TimeoutError('ack lost')
            return result
        self.b.docker.side_effect=uncertain
        with patch.object(job.validation_job,'run',return_value=self.result) as run:
            with self.assertRaises(job.validation_job.Pending):job.tick(self.b,self.key,self.fx)
            run.assert_not_called()
            state=job.tick(self.b,self.key,self.fx)
            self.assertEqual(state['materialization']['stage'],'complete')
            self.assertEqual(sum(c.args[0]=='POST' for c in self.b.docker.call_args_list),1)

    def test_stale_real_review_and_invalid_materializer_output_cannot_be_registered(self):
        self.fx.task.side_effect=lambda task,actor:self.task(actor,task,'wrong-wake',self.proposal)
        with patch.object(job.validation_job,'run') as run,self.assertRaises(ValueError):
            job.tick(self.b,self.key,self.fx)
        run.assert_not_called();self.b.docker.assert_not_called()
        self.fx.task.side_effect=None

    def test_receipt_must_preserve_contract_tests_and_false_flags(self):
        for mutation in ({'write_grant_issued':True},{'frozen_test_sha256':{}},
                         {'original_base_manifest_sha256':'0'*64},{'contract_sha256':'0'*64}):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                job.validate_receipt(self.state,self.base,dict(self.receipt,**mutation))

    def test_invalid_job_becomes_persistent_incident_without_identical_reexecution(self):
        invalid=dict(self.result,exit_code=1)
        with patch.object(job.validation_job,'run',return_value=invalid) as run:
            with self.assertRaises(ValueError):job.tick(self.b,self.key,self.fx)
            held=job.tick(self.b,self.key,self.fx)
            self.assertEqual(held['materialization']['stage'],'blocked')
            self.assertFalse(held['materialization']['incident']['automatic_retry'])
            self.assertTrue(held['author_blocked'])
            run.assert_called_once()
