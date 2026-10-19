"""Controller-owned, read-only diagnostic feedback for one current test file.

Run only in a no-network/no-credentials sandbox, never in the model worker.
The caller supplies hashes, not executable commands. This is NOT a snapshot,
test admission, TDD Red/Green, full regression or independent review receipt.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
from generic_harness_calibration import require,relative
from r3_snapshot_probe import probe
from literal_inspection_assessment import assess
import calibration_harness_protocol_probe as protocol

FALSE_FLAGS=('calibration_approved','red_approved','product_green','full_regression_suite_executed',
    'delivery_approval','author_retry_authorized','execution_authorized','python_assertions_executed',
    'python_test_module_imported','positive_reference_submitted')


def sha(value):return hashlib.sha256(value).hexdigest()


def target(root,path):
    root=Path(root);relative(path);require(not root.is_symlink() and root.is_dir())
    file=root/path
    require(not any(p.is_symlink() for p in (file,*list(file.parents)[:len(Path(path).parts)]))
        and file.is_file() and file.stat().st_size<=32768)
    return file


def capture(harness):
    matches=[(i+1,line.strip()) for i,line in enumerate(harness.splitlines())
        if re.fullmatch(r'[ \t]*snap\.poll_requests = latestCount\(\);[ \t]*',line)]
    require(len(matches)==1)
    return dict(field='poll_requests',literal='NODE_HARNESS',literal_line=matches[0][0],assignment=matches[0][1])


def run(previous,candidate,previous_manifest,test_path,candidate_sha):
    from literal_test_maintenance import slot,guarded_witness
    require(isinstance(candidate_sha,str) and re.fullmatch('[a-f0-9]{64}',candidate_sha) is not None)
    previous=Path(previous);candidate=Path(candidate);probe(previous,previous_manifest)
    path=target(candidate,test_path);raw=path.read_bytes();require(sha(raw)==candidate_sha)
    old=slot(target(previous,test_path).read_bytes(),'NODE_HARNESS');new=slot(raw,'NODE_HARNESS')
    require(old['prefix']==new['prefix'] and old['suffix']==new['suffix']
        and old['normalized']==new['normalized'] and old['methods']==new['methods'])
    where=capture(new['literal']);bound=protocol.bind(raw.decode())
    try:
        reports={}
        with tempfile.TemporaryDirectory(prefix='author-feedback-') as folder:
            for label,driver in (('unguarded',protocol.witness(bound['prefix'])),('guarded',guarded_witness(bound['prefix']))):
                file=Path(folder)/(label+'.js');file.write_text(driver)
                value=protocol.node(bound['harness']%dict(source_path=json.dumps(str(file)),source_name=json.dumps(str(file))))
                require(value.get('executed') is True)
                reports[label]={k:value[k] for k in ('initial_requests','poll_requests','stale_guard_text')}
        expected={k:bound[k] for k in ('initial_expected','poll_minimum','stale_expected')}
        ordered=reports['guarded']['stale_guard_text']==bound['stale_expected'] and reports['unguarded']['stale_guard_text']!=bound['stale_expected']
        passed=ordered and all(r['initial_requests']==bound['initial_expected'] and r['poll_requests']>=bound['poll_minimum'] for r in reports.values())
        facts=assess({'counterexample':{'facts':{'assertion_bindings':expected}}},
            dict(reports=reports,stale_witness_selectivity_passed=passed))
        failed=[field for field,key in (('initial_requests','initial_requests_passed'),('poll_requests','poll_requests_passed'),
            ('stale_guard_text','stale_ordering_passed')) if not facts[key]]
        action=('Drive polling BEFORE this assignment (snap.poll_requests = latestCount();), not the later stale-response block; '
            'preserve passing initial_requests and stale_guard_text checks and every other assertion.' if failed==['poll_requests'] else
            'Inspect the named failed fields; do not change expectations. Feedback is not approval.' if failed else
            'Fixed diagnostic checks pass for these exact bytes. Submit for independent frozen validation; this is NOT product Green or delivery approval.')
        return dict(operation='literal_author_feedback_v1',candidate_sha256=candidate_sha,
            feedback_sha256=sha(Path(__file__).read_bytes()),
            previous_manifest_sha256=previous_manifest,test_path=test_path,capture=where,
            reports=reports,expected=expected,failed_fields=failed,checks_passed=passed,next_action=action,
            outside_literal_bytes_preserved=True,candidate_bytes_stable_during_measurement=True,
            non_target_verification='not_performed_in_feedback',evidence_scope='current_file_fixed_diagnostic_only',
            model_calls=0,**{k:False for k in FALSE_FLAGS})
    finally:
        probe(previous,previous_manifest)
        require(target(candidate,test_path).read_bytes()==raw)


def main(arguments):
    try:
        require(len(arguments)==5);signal.alarm(90)
        require(not Path('/var/run/docker.sock').exists() and not any(os.environ.get(k)
            for k in ('OPENROUTER_API_KEY','OPENAI_API_KEY','GITHUB_TOKEN','GH_TOKEN','BROKER_TOKEN')))
        print(json.dumps(run(*arguments),sort_keys=True));return 0
    except Exception as error:
        print(json.dumps(dict(operation='literal_author_feedback_v1',failure=type(error).__name__,
            **{k:False for k in FALSE_FLAGS}),sort_keys=True));return 1


if __name__=='__main__':sys.exit(main(sys.argv[1:]))
