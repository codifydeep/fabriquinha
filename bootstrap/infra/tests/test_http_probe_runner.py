import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from http_probe_runner import run_probe,ProbeFailure

class ProbeTests(unittest.TestCase):
    def execute(self,fail_phase=None,functional=False):
        calls=[]; records=[]; names=[]
        def runner(cmd,timeout):
            action=cmd[1]; calls.append(action)
            if action=='create': names.append(cmd[cmd.index('--name')+1])
            if action==fail_phase and calls.count(action)==1: raise subprocess.TimeoutExpired(cmd,timeout)
            output=''
            if action=='wait': output='1' if functional else '0'
            if action=='logs': output=json.dumps(dict(passed=True,commit='sha',checks=10))
            if action=='inspect': output=json.dumps([{'Config':{'Labels':{'hermes.probe.id':cmd[-1]}}}])
            return subprocess.CompletedProcess(cmd,0,output)
        with patch('http_probe_runner.bounded_run',side_effect=runner):
            result=run_probe('image','api','sha',False,'fixed','project',lambda s:records.append(json.loads(json.dumps(s))))
        return result,calls,records
    def test_success_records_all_stages_and_cleanup(self):
        result,calls,records=self.execute()
        self.assertTrue(result['passed']); self.assertEqual(calls,['create','start','wait','logs','inspect','rm'])
        self.assertTrue(records[-1]['cleanup_ok'])
    def test_infrastructure_retry_once_after_cleanup(self):
        result,calls,records=self.execute('start')
        self.assertEqual(calls.count('create'),2); self.assertEqual(calls.count('rm'),2)
        self.assertEqual(result['lifecycle'][0]['events'][-1]['phase'],'start')
    def test_http_failure_not_retried(self):
        with self.assertRaises(ProbeFailure) as caught: self.execute(functional=True)
        self.assertEqual(len(caught.exception.detail['attempts']),1)
        self.assertEqual(caught.exception.detail['category'],'http_validation_failed')
    def test_uncertain_cleanup_blocks_retries(self):
        with patch('http_probe_runner.bounded_run',side_effect=subprocess.TimeoutExpired('docker',5)):
            with self.assertRaises(ProbeFailure) as caught:
                run_probe('image','api','sha',False,'fixed','project',lambda s:None)
        self.assertEqual(caught.exception.detail['category'],'probe_cleanup_failed')
