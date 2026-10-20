"""Calibration-only authority; never a product permission or remediation reset.

Ordinary remediation inputs use their original guard unchanged. A maintained
artifact may reuse its unchanged product brief/plan only after reauthenticating
the native maintenance review and exact source snapshots. This adapter must not
replace the product/worker runtime guard.
"""
import json
from generic_harness_calibration import digest,require


def lookup(b,issue):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='literal_maintenance_workflows'").fetchone():return None
        matches=[tuple(map(json.loads,row)) for row in con.execute('SELECT config,state FROM literal_maintenance_workflows')
            if json.loads(row[1]).get('issue_id')==issue]
    require(len(matches)<=1)
    return matches[0] if matches else None


def authenticate(b,cfg,s):
    try:import literal_maintenance_workflow as flow,literal_maintenance_effects as lane
    except ImportError:from broker import literal_maintenance_workflow as flow,literal_maintenance_effects as lane
    require(s['stage']=='maintenance_approved' and s.get('review_phase')=='escalated'
        and all(s[k] is False for k in ('functional_red','delivery_approval','source_reset'))
        and s['review']==s['escalated_review'] and s['review']['agent_id']==cfg['cto']
        and s['review']['value']['action']=='approve_test_revision'
        and s['review']['value']['manifest_sha256']==s['inspection']['candidate_manifest_sha256']
        and s['inspection']['stale_witness_selectivity_passed'] is True)
    fx=lane.Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx);flow.authenticate_escalated_review(cfg,s,fx)
    shadow={**s,'wakeup_id':s['review_wakeup'],'marker':s['review_marker']}
    actual=fx.plans.task(s['review']['task_id'],cfg['cto'])
    require(fx.decision(cfg,shadow,'escalated',actual)==s['review']
        and fx.validate_escalated_review(cfg,s,s['review'])==s['escalated_review_validation'])
    fx.validate_inspection(cfg,s,s['inspection']);fx.preserved_submission(cfg,s)
    return dict(operation='maintained_test_calibration_source_v1',config_sha256=digest(cfg),
        source_task=flow.workflow_key(cfg),author_task=s['author_task'],issue_id=s['issue_id'],
        manifest_sha256=s['inspection']['candidate_manifest_sha256'],
        test_sha256={cfg['test_path']:s['inspection']['structure']['candidate_test_sha256']},
        review_sha256=digest(s['review']),review_validation_sha256=digest(s['escalated_review_validation']),
        source_reset=False,author_retry_authorized=False,execution_authorized=False,delivery_approval=False)


def qualified(b,issue):
    try:import remediation_runtime_guard as guard
    except ImportError:from broker import remediation_runtime_guard as guard
    original=guard.qualified(b,issue)
    if original is not None:return original
    found=lookup(b,issue)
    if found is None:return None
    cfg,s=found;authenticate(b,cfg,s)
    require(cfg['source']['issue_id']!=issue)
    value=guard.qualified(b,cfg['source']['issue_id'])
    require(value and digest(value)==cfg['source']['execution_sha256']
        and value['plan_sha256']==cfg['source']['plan_sha256']
        and value['amendment']['kind']=='inherited_frozen_suite'
        and value['criteria']==cfg['source']['criteria'])
    with b.db() as con:
        parent=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(cfg['source']['issue_id'],)).fetchone()[0])
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
    try:import literal_maintenance_effects as lane
    except ImportError:from broker import literal_maintenance_effects as lane
    require(digest(parent)==cfg['route_sha256'] and route==lane.maintenance_route(parent,issue)
        and route['enabled'] is False
        and route['author']==cfg['author'] and route['cto']==cfg['cto'] and route['techlead']==cfg['reviewer'])
    return value
