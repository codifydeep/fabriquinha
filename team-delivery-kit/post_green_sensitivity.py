"""Offline v2 full-inventory sensitivity runner; no authority or native effects.

Run only in the fixed isolated test sandbox. Positive fixtures MUST equal the
Green snapshot bytes; agents propose negative data, never a second positive
implementation. Reuses the Path loader, not the old single-test calibration
receipt. Every mutant executes the complete frozen inventory again.
"""
import contextlib
import json
from pathlib import Path
import sys
import unittest

from broker import quality_lifecycle_v2 as quality
import generic_harness_calibration_v2 as loader
from calibration_frozen_harness_probe import Results,OutputDigest,cases
from generic_harness_calibration import digest as loader_digest


class Observations(Results):
    def record(self,test,outcome,error=None):
        super().record(test,outcome,error)
        value=self._observations[test.id()]
        value['path']=Path(sys.modules[test.__class__.__module__].__file__).resolve().relative_to(self.root).as_posix()
        value['method']=test._testMethodName
        if error:value['kind']='assertion' if issubclass(error[0],AssertionError) else 'exception'


def run(candidate,controls,plan,evidence,policy,expected):
    require=quality.require
    require(quality.next_stage(plan,evidence)=='sensitivity')
    green=evidence['green'];candidate=Path(candidate).resolve();controls=Path(controls).resolve()
    require(isinstance(policy,dict) and policy.get('version')=='post_green_sensitivity_policy_v2'
        and set(policy)=={'version','engine','source_task','execution_sha256','plan_sha256',
            'candidate_manifest_sha256','controls_manifest_sha256','criteria','test_sha256','modules','negatives'}
        and loader_digest(policy)==expected)
    # Reuse only the loader mechanics. Its historical-method field receives the
    # complete current inventory internally, never an attestation of old methods.
    # No legacy calibration receipt is accepted, produced or reclassified.
    mechanical={**policy,'version':'generic_harness_calibration_v2',
        'previous_methods':{m['path']:m['classes'] for m in policy['modules']}}
    loader.validate_policy(mechanical,loader_digest(mechanical))
    require(policy['plan_sha256']==quality.digest(plan)
        and policy['candidate_manifest_sha256']==green['manifest_sha256']
        and policy['test_sha256']==green['tests'] and set(policy['criteria'])==set(plan['criteria']))
    # Verify every source and control hash before comparing positive bytes.
    loader.probe(candidate,policy['candidate_manifest_sha256'])
    loader.probe(controls,policy['controls_manifest_sha256'])
    for module in policy['modules']:
        for fixture in module['fixtures']:
            require((candidate/fixture['product_path']).read_bytes()==(controls/fixture['positive_fixture']).read_bytes())
    mutations=[]
    for negative in policy['negatives']:
        module=next(m for m in policy['modules'] if m['path']==negative['module'])
        paths={f['attribute']:f['product_path'] for f in module['fixtures']}
        changed=sorted({paths[r['attribute']] for r in negative['replacements']})
        require(set(changed)<=set(plan['product_files']))
        mutations.append(changed)
    factories=[];observed=[];output=OutputDigest()
    def full_suite(suite):
        if not factories:
            for test in cases(suite):factories.append((type(test),test._testMethodName))
        require(len(factories)==green['tests_run'])
        result=Observations();result.root=candidate
        # Rebuild fresh instances, preserving precisely the complete inventory.
        unittest.TestSuite(cls(method) for cls,method in factories).run(result)
        rows=result.observations
        require(result.testsRun==len(factories)==len(rows)
            and not result.expectedFailures and not result.unexpectedSuccesses)
        facts=dict(tests=green['tests'],tests_run=result.testsRun,skipped=len(result.skipped),errors=len(result.errors),
            suite_complete=True,exit_code=0 if result.wasSuccessful() else 1,
            failures=[{k:r[k] for k in ('path','method','phase','kind')} for r in rows if r['outcome']=='failure'])
        observed.append(facts)
        return {} # Deliberately cannot be mistaken for a v1/v2 calibration receipt.
    with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
        loader.observe(candidate,controls,mechanical,loader_digest(mechanical),_observe_suite=full_suite)
    require(len(observed)==1+len(policy['negatives']))
    quality.suite(plan,observed[0],passing=True,minimum=green['tests_run'],frozen=green['tests'])
    facts=dict(operation='observed_sensitivity_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
        contract_sha256=plan['contract_sha256'],plan_sha256=quality.digest(plan),
        green_sha256=quality.digest(green),positive_sha256=quality.digest(green),
        manifest_sha256=green['manifest_sha256'],commit_sha=green['commit_sha'],
        controls=[dict(**observation,id=negative['id'],criteria=negative['criteria'],changed_files=changed)
            for negative,changed,observation in zip(policy['negatives'],mutations,observed[1:])])
    quality.qualify_sensitivity(plan,{**evidence,'sensitivity':facts})
    return dict(operation='post_green_full_inventory_sensitivity_v2',sensitivity=facts,
        positive=observed[0],policy_sha256=expected,captured_output_sha256=output.hash.hexdigest(),
        snapshot_unchanged=True,tests_unchanged=True,merge_authorized=False,delivery_approval=False)
