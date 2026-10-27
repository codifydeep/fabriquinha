"""Frozen multi-session acceptance used on both local executor targets."""
from pathlib import Path
import os
import errno
import socket
import time
from playwright.sync_api import expect
from fabriquinha_acceptance import AcceptanceTest


class Probe(AcceptanceTest):
    def test_independent_sessions_and_bounded_update(self):
        first=self.new_context();second=self.new_context();third=self.new_context()
        first.add_cookies([{'name':'isolated','value':'yes','url':self.target}])
        self.assertEqual(second.cookies(),[])
        self.assertEqual(third.cookies(),[])
        a=first.new_page();b=second.new_page()
        a.goto(self.target,wait_until='domcontentloaded');b.goto(self.target,wait_until='domcontentloaded')
        expect(a.locator('#send')).to_be_visible()
        name='probe-'+str(time.monotonic_ns())
        a.locator('#value').fill(name)
        started=time.monotonic();a.locator('#send').click()
        expect(b.locator('#observed')).to_have_text(name,timeout=2800)
        self.assertLessEqual(time.monotonic()-started,3.0)
        self.assertEqual(first.request.post(self.target+'/claim',data='first').status,200)
        self.assertEqual(second.request.post(self.target+'/claim',data='second').status,200)
        self.assertEqual(third.request.post(self.target+'/claim',data='third').status,409)

    def test_isolation(self):
        with self.assertRaises(OSError) as refused:Path(__file__).write_text('changed')
        self.assertIn(refused.exception.errno,(errno.EACCES,errno.EPERM,errno.EROFS))
        self.assertFalse(Path('/var/run/docker.sock').exists())
        for key in ('OPENROUTER_API_KEY','GH_TOKEN','GITHUB_TOKEN','TELEGRAM_BOT_TOKEN'):
            self.assertNotIn(key,os.environ)
        with socket.socket() as connection:
            connection.settimeout(0.3)
            with self.assertRaises(OSError):connection.connect(('1.1.1.1',443))
