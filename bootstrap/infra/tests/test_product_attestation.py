import importlib.util,json,subprocess,tempfile,unittest
from pathlib import Path
from product_attestation import sign

class AttestationTests(unittest.TestCase):
    def test_signature_detects_payload_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);key=root/'private';pub=root/'public'
            subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True)
            subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(pub)],check=True,capture_output=True)
            envelope=sign({'value':'reviewed'},key)
            import base64
            (root/'signature').write_bytes(base64.b64decode(envelope['signature']))
            for content,expected in [(b'{"value":"reviewed"}',0),(b'{"value":"forged"}',1)]:
                (root/'payload').write_bytes(content)
                r=subprocess.run(['openssl','pkeyutl','-verify','-pubin','-inkey',str(pub),'-rawin','-in',str(root/'payload'),'-sigfile',str(root/'signature')],capture_output=True)
                self.assertEqual(r.returncode==0,expected==0)
