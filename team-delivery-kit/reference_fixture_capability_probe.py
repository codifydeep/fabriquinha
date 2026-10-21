"""Fixed synthetic v2 capability experiment, never the product's calibration.

Demonstrates executable reference JS/HTML in separate fixtures while unfinished
candidate bytes and frozen assertions remain untouched. No model or user code
is accepted. Run in the fixed offline sandbox with no product volume mounted.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import sys
import tempfile

import calibration_control_experiment_probe as experiment
import generic_harness_calibration_v2 as engine
from generic_calibration_bundle_writer import inventory
from generic_harness_calibration import digest,require

FALSE_FLAGS=('product_snapshot_used','product_tests_executed','author_retry_authorized',
    'execution_authorized','calibration_approved','red_approved','product_green','delivery_approval')
CHECKS={'candidate_lacks_future_behavior','candidate_bytes_unchanged','frozen_assertions_unchanged',
    'separate_reference_program_executed','previous_method_preserved','negative_assertions_exercised'}
SOURCES=('generic_harness_calibration_v2','calibration_control_experiment_probe','generic_calibration_bundle_writer')
TEST='''import subprocess
import unittest
from pathlib import Path
APP_JS=Path(__file__).parents[1]/"app/app.js"
INDEX_HTML=Path(__file__).parents[1]/"app/index.html"
class ContractTests(unittest.TestCase):
 def value(self,method):
  return subprocess.check_output(["node","-e","process.stdout.write(require(process.argv[1])[process.argv[2]]())",str(APP_JS),method],text=True,timeout=10)
 def test_legacy(self):
  self.assertEqual(self.value("legacy"),"kept")
 def test_future_script(self):
  self.assertEqual(self.value("future"),"reference-only")
 def test_future_markup(self):
  self.assertIn("id=\\\"future\\\"",INDEX_HTML.read_text())
'''


def source_hashes():
    return {name:hashlib.sha256(Path(importlib.util.find_spec(name).origin).read_bytes()).hexdigest() for name in SOURCES}


def fixture_bundle():
    files={'tests/test_contract.py':TEST,'app/app.js':'module.exports={legacy:()=>"kept"};\n',
        'app/index.html':'<main id="legacy">kept</main>\n'}
    controls={'positive.js':'module.exports={legacy:()=>"kept",future:()=>"reference-only"};\n',
        'positive.html':'<main id="legacy">kept</main><div id="future">reference-only</div>\n',
        'negative.js':'module.exports={legacy:()=>"kept",future:()=>"broken"};\n',
        'negative.html':'<main id="legacy">kept</main>\n'}
    manifest=inventory(files);control_manifest=inventory(controls)
    policy=dict(version='generic_harness_calibration_v2',engine='unittest_path_fixtures_v2',
        source_task='00000000-0000-4000-8000-000000000001',execution_sha256=digest('synthetic-reference-capability'),
        plan_sha256=digest('separate-executable-reference-v1'),candidate_manifest_sha256=hashlib.sha256(manifest.encode()).hexdigest(),
        controls_manifest_sha256=hashlib.sha256(control_manifest.encode()).hexdigest(),criteria=['A01','A02'],
        test_sha256={'tests/test_contract.py':hashlib.sha256(TEST.encode()).hexdigest()},
        previous_methods={'tests/test_contract.py':{'ContractTests':['test_legacy']}},
        modules=[dict(path='tests/test_contract.py',classes={'ContractTests':['test_legacy','test_future_script','test_future_markup']},
            fixtures=[dict(attribute='APP_JS',product_path='app/app.js',positive_fixture='positive.js'),
                dict(attribute='INDEX_HTML',product_path='app/index.html',positive_fixture='positive.html')])],
        negatives=[dict(id='script',module='tests/test_contract.py',class_name='ContractTests',method='test_future_script',
                replacements=[dict(attribute='APP_JS',fixture='negative.js')],criteria=['A01']),
            dict(id='markup',module='tests/test_contract.py',class_name='ContractTests',method='test_future_markup',
                replacements=[dict(attribute='INDEX_HTML',fixture='negative.html')],criteria=['A02'])])
    bundle=dict(operation='generic_calibration_proposal_bundle_v1',policy=policy,policy_sha256=digest(policy),
        controls=controls,controls_manifest=control_manifest,execution_authorized=False,delivery_approval=False)
    return files,bundle


def validate(value):
    files,bundle=fixture_bundle();policy=bundle['policy']
    require(set(value)=={'operation','synthetic','checks','measurements','negative_failure_phases','script_sha256',
        'source_hashes','model_calls',*FALSE_FLAGS}
        and value['operation']=='synthetic_executable_reference_capability_v1' and value['synthetic'] is True
        and value['source_hashes']==source_hashes()
        and value['script_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        and type(value['model_calls']) is int and value['model_calls']==0
        and set(value['checks'])==CHECKS and all(v is True for v in value['checks'].values())
        and value['negative_failure_phases']=={'script':'test_body','markup':'test_body'}
        and all(value[k] is False for k in FALSE_FLAGS))
    require(value['measurements']['status']=='observed')
    engine.validate_receipt({**value['measurements'],'status':'passed'},policy,digest(policy))
    return value


def run():
    # Imported immutable test modules must never add __pycache__ to snapshots.
    before_bytecode=sys.dont_write_bytecode;sys.dont_write_bytecode=True
    try:
        files,bundle=fixture_bundle()
        with tempfile.TemporaryDirectory(prefix='reference-capability-') as directory:
            root=Path(directory)/'candidate';root.mkdir()
            for name,text in files.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            (root/'manifest.json').write_text(inventory(files))
            before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result=experiment.run(root,bundle,digest(bundle))
            after={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            require(result['functional_controls_passed'] is True and before==after)
            checks=dict(candidate_lacks_future_behavior='future' not in files['app/app.js'] and 'future' not in files['app/index.html'],
                candidate_bytes_unchanged=before==after,frozen_assertions_unchanged=(root/'tests/test_contract.py').read_text()==TEST,
                separate_reference_program_executed=result['measurements']['positive']['failures']==0,
                previous_method_preserved=result['measurements']['positive']['tests']==3,
                negative_assertions_exercised=result['negative_failure_phases']=={'script':'test_body','markup':'test_body'})
        return validate(dict(operation='synthetic_executable_reference_capability_v1',synthetic=True,checks=checks,
            measurements=result['measurements'],negative_failure_phases=result['negative_failure_phases'],
            script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),source_hashes=source_hashes(),model_calls=0,
            **{k:False for k in FALSE_FLAGS}))
    finally:sys.dont_write_bytecode=before_bytecode


if __name__=='__main__':
    require(len(sys.argv)==1);signal.alarm(60)
    print(json.dumps(run(),sort_keys=True))
