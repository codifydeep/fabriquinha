"""Controller-only signing of already reviewed exact-source test maintenance."""
import base64,hashlib,json,subprocess,tempfile
from pathlib import Path
from product_workspace import digest

RECEIPT_PATH='.hermes/reviewed-test-maintenance.json'
PUBLIC_PATH='scripts/ci/test-maintenance-public.pem'

def canonical(payload):return json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
def sign(payload,key):
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'payload';path.write_bytes(canonical(payload))
        signature=subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(path)],capture_output=True,check=True).stdout
    return dict(payload=payload,signature=base64.b64encode(signature).decode(),algorithm='Ed25519')

def prepare(c,card,packet,base):
    maintenance=card.get('reviewed_test_maintenance')
    if not maintenance:return None
    row=c.private.execute('SELECT receipt FROM test_maintenance_applied WHERE proposal_sha=? AND attempt=?',(maintenance['proposal_sha256'],c.cfg['attempt'])).fetchone()
    if not row:raise PermissionError('applied reviewed maintenance proof missing')
    receipt=json.loads(row[0]);proposal=receipt['proposal'];verdict=receipt['verdict'];validation=receipt['validation']
    if digest(proposal)!=maintenance['proposal_sha256'] or verdict['proposal_sha256']!=digest(proposal) or verdict['decision']!='approve' or proposal['author']==verdict['reviewer'] or validation['reviewer']!=verdict['reviewer']:raise PermissionError('maintenance proof provenance')
    replacements=proposal['specification']['replacements']
    if any(packet['files'].get(n)!=v for n,v in replacements.items()):raise PermissionError('reviewed tests changed after maintenance')
    allowed=sorted(set(replacements)|set(proposal['specification']['renames']))
    payload=dict(version=1,attempt=c.cfg['attempt'],base=base,task=packet['task'],revision=packet['revision'],
        proposal_sha256=digest(proposal),author=proposal['author'],reviewer=verdict['reviewer'],review_run=verdict['run'],
        allowed_test_paths=allowed,source_manifest={n:hashlib.sha256(v.encode()).hexdigest() for n,v in packet['files'].items()},
        removed_paths=sorted(proposal['specification']['renames']),case_coverage=validation['coverage'],
        snapshot_validation=packet['validation_sha256'],scope='reviewed_test_maintenance_only')
    return sign(payload,c.root/'signing/test-maintenance-private.pem')
