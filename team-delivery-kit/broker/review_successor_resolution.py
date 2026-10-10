"""Resolve only a withdrawn successor hold after exact independent R1 approval.

No route activation, restored retry budget, task restart or product approval.
"""
import copy
import json
try:from technical_remediation_plan import digest
except ImportError:from broker.technical_remediation_plan import digest


def prepare(source,parent,contract,admission,successor_config,successor,trial):
    proof=successor.get('review_mediation_withdrawal',{})
    gate=parent.get('r1_gate',{});red=gate.get('red',{})
    original=admission.get('superseded_admission',{})
    if (admission.get('stage')!='blocked' or admission.get('category')!='superseded_by_r1_feedback'
            or successor.get('stage')!='blocked'
            or successor.get('category')!='withdrawn_for_immutable_review_mediation'
            or proof.get('operation')!='unstarted_feedback_successor_withdrawal_v1'
            or proof.get('parent_source')!=source or proof.get('source_task')!=red.get('task_id')
            or admission.get('next_source')!=red.get('task_id')
            or proof.get('prior_admission')!=admission or proof.get('prior_config')!=successor_config
            or proof.get('config_sha256')!=digest(successor_config)
            or proof.get('prior_parent_contract')!=contract
            or contract.get('source_task')!=source or contract.get('original_depth')!=2
            or parent.get('contract_sha256')!=digest(contract)
            or parent.get('superseded_by_feedback')!={'source_task':red.get('task_id'),'config_sha256':digest(successor_config)}
            or parent.get('stage')!='r1_base_qualified' or parent.get('execution_authorized') is not False
            or gate.get('operation')!='immutable_remediation_r1_gate_v1'
            or gate.get('execution_contract_sha256')!=digest(contract)
            or gate.get('run_id')!=contract.get('run_id')
            or gate.get('product_execution_authorized') is not False or gate.get('release_homologated') is not False
            or trial.get('status')!='approved' or trial.get('source_task')!=red.get('task_id')
            or trial.get('manifest_sha256')!=red.get('red',{}).get('manifest_sha256')
            or trial.get('review_task')!=gate.get('review_task') or not trial.get('review_task')
            or trial.get('review_task')==red.get('task_id')
            or trial.get('decision')!=gate.get('review_decision')
            or trial.get('decision',{}).get('action')!='approve_test_revision'
            or trial.get('decision',{}).get('findings')!=[]
            or trial.get('decision',{}).get('manifest_sha256')!=trial.get('manifest_sha256')
            or trial.get('review_reconsideration',{}).get('operation')!='immutable_review_reconsideration_v1'
            or trial['review_reconsideration'].get('manifest_sha256')!=trial.get('manifest_sha256')
            or trial['review_reconsideration'].get('delivery_approval') is not False
            or trial['review_reconsideration'].get('test_changes_authorized') is not False
            or original.get('stage')!='phases_admitted' or original.get('budget_admitted') is not True
            or original.get('release_homologated') is not False
            or set(original.get('steps',{}))!={'R1'}
            or original['steps']['R1'].get('issue_id')!=red.get('issue_id')
            or proof.get('tasks_observed')!=0 or proof.get('wakeups_observed')!=0
            or proof.get('revision_depth_reset') is not False):
        raise ValueError('exact withdrawn successor and independently approved unchanged R1 required')
    restored=copy.deepcopy(original)
    restored['withdrawn_successor_resolution']=dict(operation='approved_r1_withdrawn_successor_resolution_v1',
        prior_admission=copy.deepcopy(admission),successor_sha256=digest(successor),
        review_task=trial['review_task'],manifest_sha256=trial['manifest_sha256'],
        r1_gate_sha256=digest(gate),consumed_feedback_round=proof['consumed_feedback_round'],
        phase_activated=False,author_restarted=False,release_homologated=False)
    return restored


def resolve(b,source,fx):
    try:import remediation_test_review as review,native
    except ImportError:from broker import remediation_test_review as review,native
    with b.db() as c:
        admission=json.loads(c.execute('SELECT state FROM remediation_admissions WHERE source_task=?',(source,)).fetchone()[0])
        contract,parent=map(json.loads,c.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone())
        next_source=admission['next_source']
        config,successor=map(json.loads,c.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(next_source,)).fetchone())
        issue=parent['issue_id']
        trial=json.loads(c.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])
        route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
    restored=prepare(source,parent,contract,admission,config,successor,trial)
    fx.plan(source)  # Actual original independent CTO/TL plan, unchanged scope.
    red=parent['r1_gate']['red'];review.verify(b,issue,route,red,fx.native)
    task=native.task_record(fx.native.settings,trial['review_task'],route['techlead'])
    if (task.get('status')!='completed' or task.get('issue_id')!=issue
            or task.get('wakeup_id')!=trial.get('wakeup_id') or task.get('agent_id')==route['author']
            or fx.native.decision(task)!=trial['decision']):
        raise ValueError('actual same-snapshot independent review required')
    with b.db() as c:
        for table,key,expected in (
                ('remediation_admissions',source,admission),('remediation_executions',source,parent),
                ('technical_remediation_plans',next_source,successor)):
            if json.loads(c.execute('SELECT state FROM '+table+' WHERE source_task=?',(key,)).fetchone()[0])!=expected:
                raise ValueError('withdrawal resolution changed before commit')
        if json.loads(c.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])!=trial:
            raise ValueError('R1 approval changed before commit')
        if (json.loads(c.execute('SELECT contract FROM remediation_executions WHERE source_task=?',(source,)).fetchone()[0])!=contract
                or json.loads(c.execute('SELECT config FROM technical_remediation_plans WHERE source_task=?',(next_source,)).fetchone()[0])!=config
                or json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])!=route):
            raise ValueError('withdrawal contract or route changed before commit')
        c.execute('UPDATE remediation_admissions SET state=? WHERE source_task=?',(json.dumps(restored,sort_keys=True),source))
    return restored
