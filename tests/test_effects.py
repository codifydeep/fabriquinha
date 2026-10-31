import sys
import tempfile
import unittest
import subprocess
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fabriquinha.effects import Journal, Pending, EffectBlocked


class EffectRecovery(unittest.TestCase):
    def test_process_exit_after_effect_before_ack_reconciles_without_resend(self):
        # A real terminated process, but a filesystem stand-in for the external
        # service. This is journal coverage, not Docker/deployment qualification.
        root=Path(self.temp.name)
        script='''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from fabriquinha.effects import Journal, write_json
root=Path(sys.argv[1])
def send():
    write_json(root/'external-resource.json', {'handle':'created-once','sha':'one'})
    os._exit(23)
Journal(root/'journal').do('deploy', {'sha':'one'}, send, lambda: None)
'''
        result=subprocess.run([sys.executable,'-c',script,str(root),
            str(Path(__file__).resolve().parents[1]/'src')],timeout=10,check=False)
        self.assertEqual(result.returncode,23)
        path=next((root/'journal').glob('*.json'))
        before=json.loads(path.read_bytes());self.assertEqual(before['state'],'intent')
        original=(root/'external-resource.json').read_bytes()
        def resend():self.fail('an uncertain external effect was resent')
        def observe():return json.loads((root/'external-resource.json').read_bytes())
        restarted=Journal(root/'journal')
        self.assertEqual(restarted.do('deploy',{'sha':'one'},resend,observe),observe())
        after=json.loads(path.read_bytes())
        self.assertEqual(after['state'],'done')
        self.assertEqual(after['started'],before['started'])
        self.assertEqual(after['deadline'],before['deadline'])
        self.assertEqual((root/'external-resource.json').read_bytes(),original)
        self.assertEqual(restarted.do('deploy',{'sha':'one'},resend,
            lambda:self.fail('completed effect should use its receipt')),observe())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = [100.0]
        self.journal = Journal(Path(self.temp.name), clock=lambda: self.clock[0])

    def test_lost_ack_observes_original_effect_without_repeating(self):
        sent = []
        def send():
            sent.append('original')
            raise TimeoutError()
        with self.assertRaises(Pending):
            self.journal.do('create', {'revision': 1}, send, lambda: None)
        self.assertEqual(self.journal.do('create', {'revision': 1}, send,
                                        lambda: {'handle': 'original'}), {'handle': 'original'})
        self.assertEqual(sent, ['original'])

    def test_observation_deadline_does_not_reset_on_restart(self):
        sent = []
        def send():
            sent.append(True)
            raise TimeoutError()
        with self.assertRaises(Pending):
            self.journal.do('job', {}, send, lambda: None, timeout=10)
        self.clock[0] = 111
        restarted = Journal(Path(self.temp.name), clock=lambda: self.clock[0])
        with self.assertRaises(EffectBlocked):
            restarted.do('job', {}, send, lambda: None, timeout=10)
        self.assertEqual(len(sent), 1)

    def test_same_key_cannot_be_reused_for_another_revision(self):
        self.journal.do('deploy', {'sha': 'one'}, lambda: {'image': 'one'}, lambda: None)
        with self.assertRaises(ValueError):
            self.journal.do('deploy', {'sha': 'two'}, lambda: {'image': 'two'}, lambda: None)


if __name__ == '__main__':
    unittest.main()
