"""Finalize a release only after native completion and immutable evidence.

The ledger state is authoritative. No gateway text or heartbeat is proof.
"""
import json
from pathlib import Path
from delivery_receipts import EvidenceStore


def finalize(conn,config,store,registry=None,evidence_root='/opt/data/governance/evidence'):
    attempt=config['attempt']
    row=store.db.execute('SELECT board,state FROM attempts WHERE id=?',(attempt,)).fetchone()
    if not row or row['board']!=config['board']:
        raise ValueError('release attempt/board mismatch')
    if row['state']!='EM_HOMOLOGACAO':
        return False
    if registry is None:
        registry=json.loads(Path('/opt/data/governance/active-release.json').read_text())
    if registry.get('attempt')!=attempt or registry.get('board')!=config['board']:
        raise ValueError('active release identity mismatch')
    controller=registry['controller']
    task=conn.execute('SELECT status FROM tasks WHERE id=?',(controller,)).fetchone()
    if not task or task['status']!='done':
        return False
    required=registry.get('mandatory_tasks')
    if required is not None:
        if not isinstance(required,list) or not required or controller not in required or any(not isinstance(t,str) for t in required) or len(set(required))!=len(required):
            raise ValueError('explicit unique mandatory release scope required')
        for tid in required:
            state=conn.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()
            if not state or state['status']!='done':return False
    elif conn.execute("SELECT 1 FROM tasks WHERE status NOT IN ('done','archived') LIMIT 1").fetchone():
        # Preserve old registrations; only a reviewed new registry narrows scope.
        return False
    reference=store.get(attempt,'delivery_receipt',controller)
    if not reference or reference.get('kind')!='homologation':
        raise ValueError('completed controller has no homologation receipt')
    proof=EvidenceStore(evidence_root,attempt).load(reference['sha256'])
    if proof.get('kind')!='homologation' or proof.get('task')!=controller:
        raise ValueError('receipt does not attest this release controller')
    if proof.get('criteria')!=registry.get('approved_criteria') or not proof.get('artifacts'):
        raise ValueError('receipt lacks approved scope or durable artifacts')
    report=proof['report']
    if not proof.get('commit') or report.get('commit')!=proof['commit']:
        raise ValueError('receipt commit mismatch')
    message=json.dumps(dict(profile='techlead',chat_id=config['chat_id'],text=
        f"✅ HOMOLOGADA — {registry['branch']}\nURL: {report['url']}\nCommit: {proof['commit']}\n"
        f"Controlador: {controller}\nRecibo: {reference['sha256']}"))
    store.transition(attempt,'EM_HOMOLOGACAO','HOMOLOGADA','techlead',
        dict(receipt=reference['sha256'],controller=controller),
        notification=('release:homologated',message))
    return True
