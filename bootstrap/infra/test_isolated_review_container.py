"""Run only in a disposable controller container with its own test volume."""
import os
from pathlib import Path
import tempfile
from review_controller import Controller

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp); board=root/'board'; board.mkdir(); work=root/'work'; work.mkdir()
    (work/'test_isolation.py').write_text('''import unittest
from pathlib import Path
class Isolation(unittest.TestCase):
    def test_readonly(self):
        with self.assertRaises(OSError): Path('/delivery/new-file').write_text('bad')
    def test_no_docker(self): self.assertFalse(Path('/var/run/docker.sock').exists())
    def test_no_hermes(self):
        try: self.assertFalse(Path('/opt/data/profiles').exists())
        except PermissionError: pass
    def test_no_store(self): self.assertFalse(Path('/deliveries/controller.db').exists())
    def test_no_network(self):
        import socket
        with socket.socket() as connection:
            connection.settimeout(1)
            with self.assertRaises(OSError): connection.connect(('192.0.2.1',9))
        routes=Path('/proc/net/route').read_text().splitlines()[1:]
        self.assertFalse(any(line.split()[1]=='00000000' for line in routes))
    def test_temp(self):
        p=Path('/tmp/test-output'); p.write_text('ok'); self.assertEqual(p.read_text(),'ok')
''')
    controller=Controller(board,'/deliveries','isolated','hermes_review_acceptance_20260912','estudo-hermes-saas:0.21.16')
    try:
        revision=controller.store.capture(work,attempt='isolated',task='t_test',author='backend_data',run=1)
        result=controller.validate('t_test',revision)
        print(result)
        assert result['passed'],result
        controller.store.load('isolated','t_test',revision)
        print('PASS: real Docker review is read-only, offline, without credentials/socket; scratch output works')
    finally: controller.db.close()
