"""Real DOM behavior assertion plus delivery write/credential denial."""
import os
import errno
from pathlib import Path
import subprocess
import sys
import unittest
from playwright.sync_api import sync_playwright, expect


class CounterBehavior(unittest.TestCase):
    def stop_server(self):
        self.process.terminate()
        self.process.communicate(timeout=3)

    def setUp(self):
        self.process = subprocess.Popen([sys.executable, '-B', '/workspace/app.py', '0'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_server)
        self.port = int(self.process.stdout.readline())
        driver = sync_playwright().start()
        self.addCleanup(driver.stop)
        self.browser = driver.chromium.launch(headless=True)
        self.addCleanup(self.browser.close)

    def test_click_changes_dom_not_just_source_tokens(self):
        self.assertEqual(os.geteuid(), 65534)
        self.assertFalse(Path('/var/run/docker.sock').exists())
        for name in ('OPENROUTER_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN', 'TELEGRAM_BOT_TOKEN'):
            self.assertNotIn(name, os.environ)
        with self.assertRaises(OSError) as denied:
            Path('/workspace/app.py').write_text('not permitted')
        self.assertIn(denied.exception.errno, (errno.EACCES, errno.EPERM, errno.EROFS))
        page = self.browser.new_page()
        page.goto(f'http://127.0.0.1:{self.port}/')
        expect(page.locator('#count')).to_have_text('0', timeout=1000)
        page.locator('#increment').click(timeout=1000)
        expect(page.locator('#count')).to_have_text('1', timeout=1000)
