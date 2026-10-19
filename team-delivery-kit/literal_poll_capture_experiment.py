"""Fixed capture-timing counterfactuals, never an author submission or approval.

Only run in the readonly, no-network/no-credentials validation sandbox. The
original and two in-memory templates execute against the same two diagnostic
drivers. No snapshot, Python assertion or product implementation is modified.
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
import calibration_harness_protocol_probe as protocol


def sha(value):return hashlib.sha256(value).hexdigest()


def variants(harness):
    anchor='  snap.poll_requests = latestCount();\n'
    require(isinstance(harness,str) and 0<len(harness.encode())<=32768 and '\r' not in harness
        and harness.count(anchor)==1)
    poll='  tick();\n  await flush();\n'
    return dict(original=harness,before_capture=harness.replace(anchor,poll+anchor),
        after_capture=harness.replace(anchor,anchor+poll))


def supports(bound,reports):
    require(set(reports)=={'original','before_capture','after_capture'})
    for variant in reports.values():
        require(set(variant)=={'guarded','unguarded'})
        for value in variant.values():
            require(set(value)=={'initial_requests','poll_requests','stale_guard_text'}
                and type(value['initial_requests']) is int and type(value['poll_requests']) is int
                and isinstance(value['stale_guard_text'],str))
    preserved=all(r['guarded']['stale_guard_text']==bound['stale_expected']
        and r['unguarded']['stale_guard_text']!=bound['stale_expected']
        and all(x['initial_requests']==bound['initial_expected'] for x in r.values()) for r in reports.values())
    causal=all(reports['original'][driver]['poll_requests']<bound['poll_minimum']
        and reports['after_capture'][driver]['poll_requests']==reports['original'][driver]['poll_requests']
        and reports['before_capture'][driver]['poll_requests']==reports['original'][driver]['poll_requests']+1
        and reports['before_capture'][driver]['poll_requests']>=bound['poll_minimum'] for driver in ('guarded','unguarded'))
    return preserved and causal


def run(candidate,manifest,test_path,diagnosis_sha):
    # Only the sandbox executes templates. The controller imports supports()
    # for receipt classification without needing sandbox-only dependencies.
    from literal_test_maintenance import guarded_witness,slot
    candidate=Path(candidate);relative(test_path)
    require(test_path.endswith('.py') and re.fullmatch('[a-f0-9]{64}',diagnosis_sha) is not None)
    probe(candidate,manifest)
    try:
        raw=(candidate/test_path).read_bytes();literal=slot(raw,'NODE_HARNESS');bound=protocol.bind(raw.decode())
        require(bound['harness']==literal['literal']);templates=variants(bound['harness']);reports={};witnesses={}
        with tempfile.TemporaryDirectory(prefix='poll-capture-experiment-') as folder:
            for variant,harness in templates.items():
                reports[variant]={}
                for driver,source in (('unguarded',protocol.witness(bound['prefix'])),('guarded',guarded_witness(bound['prefix']))):
                    target=Path(folder)/(driver+'.js');target.write_text(source);witnesses[driver]=sha(source.encode())
                    value=protocol.node(harness%dict(source_path=json.dumps(str(target)),source_name=json.dumps(str(target))))
                    require(value.get('executed') is True)
                    reports[variant][driver]={k:value[k] for k in ('initial_requests','poll_requests','stale_guard_text')}
        bindings={k:bound[k] for k in ('initial_expected','poll_minimum','stale_expected')}
        return dict(operation='literal_poll_capture_counterfactual_v1',candidate_manifest_sha256=manifest,
            test_path=test_path,test_sha256=sha(raw),diagnosis_sha256=diagnosis_sha,
            assertion_bindings=bindings,reports=reports,hypothesis_supported=supports(bindings,reports),
            template_sha256={k:sha(v.encode()) for k,v in templates.items()},witness_sha256=witnesses,
            experiment_sha256=sha(Path(__file__).read_bytes()),snapshot_unchanged=True,
            counterfactual_templates_only=True,model_calls=0,**{k:False for k in protocol.FALSE_FLAGS})
    finally:probe(candidate,manifest)


def main(arguments):
    try:
        require(len(arguments)==4);signal.alarm(120)
        require(not Path('/var/run/docker.sock').exists() and not any(os.environ.get(k)
            for k in ('OPENROUTER_API_KEY','OPENAI_API_KEY','GITHUB_TOKEN','GH_TOKEN','BROKER_TOKEN')))
        value=run(*arguments)
        print(json.dumps(value,sort_keys=True));return 0
    except Exception as error:
        print(json.dumps(dict(operation='literal_poll_capture_counterfactual_v1',failure=type(error).__name__,
            **{k:False for k in protocol.FALSE_FLAGS}),sort_keys=True));return 1


if __name__=='__main__':sys.exit(main(sys.argv[1:]))
