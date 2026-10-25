import json
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.request import urlopen


class Existing(unittest.TestCase):
    def test_existing_health(self):
        process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).parents[1]/'app.py'), '0'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            port = int(process.stdout.readline())
            with urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as response:
                self.assertEqual(json.load(response), {'status': 'ok'})
        finally:
            process.terminate()
            process.communicate(timeout=3)
