"""Explicit synthetic Linux/Node canary; never imports or changes product files."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from generic_harness_calibration import digest
from generic_calibration_bundle_writer import inventory
from calibration_control_experiment_probe import run,validate


def main():
    root_mounts=[line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines() if line.split()[4]=='/']
    assert len(root_mounts)==1 and 'ro' in root_mounts[0][5].split(',')
    assert not Path('/var/run/docker.sock').exists()
    assert not any(os.environ.get(k) for k in ('OPENROUTER_API_KEY','GITHUB_TOKEN','GH_TOKEN','BROKER_TOKEN'))
    try:
        descriptor=os.open('/qualification-root-write-sentinel',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except OSError:pass
    else:os.close(descriptor);raise AssertionError('readonly root required')
    with tempfile.TemporaryDirectory(prefix='control-experiment-canary-') as temporary:
        candidate=Path(temporary)/'candidate';candidate.mkdir();(candidate/'tests').mkdir();(candidate/'app').mkdir()
        test='''import unittest,subprocess
from pathlib import Path
APP_JS=Path(__file__).parents[1]/'app/app.js'
INDEX_HTML=Path(__file__).parents[1]/'app/index.html'
class ReferenceTests(unittest.TestCase):
 def test_script(self):
  result=subprocess.run(['node',str(APP_JS)],capture_output=True,check=True)
  self.assertEqual(result.stdout,b'good')
 def test_markup(self):self.assertEqual(INDEX_HTML.read_text(),'good')
'''
        files={'tests/test.py':test,'app/app.js':'process.stdout.write("original");','app/index.html':'original'}
        for name,text in files.items():(candidate/name).write_text(text)
        manifest=inventory(files);(candidate/'manifest.json').write_text(manifest)
        controls={'positive.js':'process.stdout.write("good");','negative.js':'process.stdout.write("bad");',
            'positive.html':'good','negative.html':'bad'}
        controls_manifest=inventory(controls)
        policy=dict(version='generic_harness_calibration_v2',engine='unittest_path_fixtures_v2',
            source_task='11111111-1111-4111-8111-111111111111',execution_sha256='a'*64,plan_sha256='b'*64,
            candidate_manifest_sha256=hashlib.sha256(manifest.encode()).hexdigest(),
            controls_manifest_sha256=hashlib.sha256(controls_manifest.encode()).hexdigest(),criteria=['A01','A02'],
            test_sha256={'tests/test.py':hashlib.sha256(test.encode()).hexdigest()},
            previous_methods={'tests/test.py':{'ReferenceTests':['test_script','test_markup']}},
            modules=[dict(path='tests/test.py',classes={'ReferenceTests':['test_script','test_markup']},fixtures=[
                dict(attribute='APP_JS',product_path='app/app.js',positive_fixture='positive.js'),
                dict(attribute='INDEX_HTML',product_path='app/index.html',positive_fixture='positive.html')])],
            negatives=[dict(id=label,module='tests/test.py',class_name='ReferenceTests',method=method,
                replacements=[dict(attribute=attribute,fixture=fixture)],criteria=[criterion])
                for label,method,attribute,fixture,criterion in (
                    ('script','test_script','APP_JS','negative.js','A01'),('markup','test_markup','INDEX_HTML','negative.html','A02'))])
        bundle=dict(operation='generic_calibration_proposal_bundle_v1',policy=policy,policy_sha256=digest(policy),
            controls=controls,controls_manifest=controls_manifest,execution_authorized=False,delivery_approval=False)
        result=run(candidate,bundle,digest(bundle));validate(result,dict(prepared=dict(manifest_sha256=policy['candidate_manifest_sha256'],test_sha256=policy['test_sha256'])),bundle)
        assert result['functional_controls_passed'] and result['negative_failure_phases']=={'script':'test_body','markup':'test_body'}
        print(json.dumps(dict(operation='reference_control_node_canary_v1',positive_tests=result['measurements']['positive']['tests'],
            negative_controls=len(result['measurements']['negative_controls']),negative_failure_phases=result['negative_failure_phases'],
            readonly_root=True,no_docker_socket=True,no_credentials=True,model_calls=0,
            product_snapshot_used=False,autonomous_delivery_qualified=False,delivery_approval=False)))


if __name__=='__main__':main()
