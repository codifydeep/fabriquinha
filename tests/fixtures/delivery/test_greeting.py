import json
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen


class Greeting(unittest.TestCase):
    def test_named_greeting(self):
        process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).parents[1]/'app.py'), '0'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            port = int(process.stdout.readline())
            try:
                with urlopen(f'http://127.0.0.1:{port}/greeting?name=Ada', timeout=3) as response:
                    status, value = response.status, json.load(response)
            except HTTPError as response:
                status, value = response.code, json.load(response)
            self.assertEqual(status, 200, 'new greeting behavior must exist')
            self.assertEqual(value, {'message': 'Hello, Ada'})
        finally:
            process.terminate()
            process.communicate(timeout=3)
