"""Persist probe -> native registration -> fixed calibration, never author Red.

Jobs own their durable Docker intentions. This coordinator observes those same
jobs after transient errors; invalid evidence becomes an owned technical hold.
calibration_ready is a prerequisite, not a completed product card or release.
"""
import hashlib
import json
import time

from generic_harness_calibration import digest
from calibration_policy_adapter import validate_receipt
try:import generic_calibration_gate as gate
except ImportError:from broker import generic_calibration_gate as gate


def advance(con,c,fx,*,now=None):
    now=time.time() if now is None else now
    row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    gate.require(row and json.loads(row[0])==c);s=json.loads(row[1])
    if s['stage'] in ('blocked','calibration_ready'):return s
    gate.require(s['stage'] in ('inputs_ready','observe_inputs','register_policy','observe_calibration'))
    def save(**changes):
        s.update(changes)
        con.execute('UPDATE generic_calibration_workflows SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),c['issue_id'],c['author_task']));con.commit();return s
    def hold(category):
        return save(stage='blocked',category=category,owner=c['cto'],
            required_action='CTO diagnose exact '+category+' evidence; retain original jobs and never repeat effects')
    if 'pipeline_started' not in s:save(pipeline_started=now)
    if now-s['pipeline_started']>=1800:return hold('calibration_prerequisite_deadline')
    try:
        fx.verify(c);intake=fx.pipeline_intake(c,s)
        gate.require(digest(intake)==s['intake_sha256'] and digest(intake['policy'])==s['policy_sha256'])
    except TimeoutError:return s
    except (ValueError,KeyError,TypeError):return hold('calibration_intake_binding_rejected')
    if s['stage']=='inputs_ready':
        save(stage='observe_inputs',owner=c['cto'],required_action='Observe fixed readonly input probe; not TDD Red')
    if s['stage']=='observe_inputs':
        try:
            result=fx.input_probe(c,s,intake)
            raw=result['output']
            gate.require(type(result['exit_code']) is int and result['exit_code']==0
                and result['approval'] is False and isinstance(raw,str)
                and hashlib.sha256(raw.encode()).hexdigest()==result['output_sha256'])
        except TimeoutError:return s
        except (ValueError,KeyError,TypeError):return hold('calibration_input_probe_rejected')
        return save(stage='register_policy',input_result_sha256=digest(result),
            required_action='Revalidate actual native approvals and input proof before immutable policy registration')
    try:
        record=(fx.register_policy if s['stage']=='register_policy' else fx.registered_policy)(c,s,intake)
        gate.require(record['operation']=='generic_calibration_registration_v1'
            and record['policy']==intake['policy'] and record['context']==intake['context']
            and record['policy_sha256']==s['policy_sha256']
            and record['approvals']['propose_calibration']['task_id']==intake['proposal_task']
            and record['approvals']['approve_calibration']['task_id']==intake['review_task']
            and record['execution_authorized'] is False and record['delivery_approval'] is False)
        if s['stage']=='observe_calibration':gate.require(digest(record)==s['registration_sha256'])
    except TimeoutError:return s
    except (ValueError,KeyError,TypeError):return hold('calibration_registration_rejected')
    if s['stage']=='register_policy':
        return save(stage='observe_calibration',registration_sha256=digest(record),
            required_action='Observe original fixed sandbox calibration job; no product approval')
    try:
        result=fx.calibrate(c,s,record)
        gate.require(result['delivery_approval'] is False)
        receipt=validate_receipt(result['receipt'],intake['policy'],s['policy_sha256'])
    except TimeoutError:return s
    except (ValueError,KeyError,TypeError):return hold('calibration_actual_job_rejected')
    return save(stage='calibration_ready',calibration_result_sha256=digest(result),calibration_receipt=receipt,
        required_action='Controller may evaluate original author Red through its separate gate; no author respawn or delivery approval')
