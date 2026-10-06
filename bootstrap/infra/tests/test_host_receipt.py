import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import host_receipt as h

class HostTests(unittest.TestCase):
    def test_old_then_current_receipt(self):
        old=dict(origin='macOS-host',url='local',commit='old',at=100,passed=True,checks=10)
        good=dict(old,commit='new'); records=[]
        with patch.object(Path,'read_text',side_effect=[json.dumps(old),json.dumps(good)]),patch.object(h.time,'time',return_value=100),patch.object(h.time,'sleep'):
            result=h.wait_receipt('unused','new','local',records.append)
        self.assertEqual(result['commit'],'new'); self.assertEqual(records[0]['reason'],'wrong_commit')
    def test_timeout_preserves_observed_receipt(self):
        bad=dict(origin='macOS-host',url='local',commit='old',at=100,passed=True,checks=10)
        with patch.object(Path,'read_text',return_value=json.dumps(bad)),patch.object(h.time,'time',return_value=100):
            with self.assertRaises(h.HostReceiptPending) as caught: h.wait_receipt('x','new','local',lambda _:None,timeout=0)
        self.assertEqual(caught.exception.detail['observed'],bad)
        self.assertFalse(caught.exception.detail['ceo_required'])
    def test_wrong_url_rejected(self):
        bad=dict(origin='macOS-host',url='other',commit='new',at=100,passed=True,checks=10)
        with patch.object(Path,'read_text',return_value=json.dumps(bad)):
            with self.assertRaises(h.HostReceiptPending) as caught: h.wait_receipt('x','new','local',lambda _:None,timeout=0)
        self.assertEqual(caught.exception.detail['reason'],'wrong_url')
