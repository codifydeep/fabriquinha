"""Evidence-bound documentation for the isolated score-function rehearsal.

This is a closed claim schema, NOT a general natural-language truth detector.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from contextlib import closing

CLAIMS={'scope':'score_function_only','rule':'a_then_b','deployment':'no_evidence'}

def check_claims(content):
    try: claims=json.loads(content)
    except (TypeError,ValueError): raise ValueError('Use only the JSON claims schema: '+json.dumps(CLAIMS))
    if claims!=CLAIMS: raise ValueError('unsupported delivery claims; expected '+json.dumps(CLAIMS))

def render(root,task):
    root=Path(root)
    green=json.loads((root/'runner-green.json').read_text())
    if green.get('accepted') is not True or green.get('tests_run')!=6 or green.get('returncode')!=0:
        raise ValueError('accepted six-test Green evidence required')
    code=hashlib.sha256((root/'score.py').read_bytes()).hexdigest()
    if code!=green.get('score_sha256'): raise ValueError('code differs from Green evidence')
    tests=[]
    for name,expected in sorted(green['tests_sha256'].items()):
        if Path(name).name!=name: raise ValueError('invalid test evidence path')
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected: raise ValueError('test evidence differs')
        tests.append(f'- `{name}`: `{expected}`')
    return f'''# Delivery evidence — isolated score-function rehearsal

Card: `{task}`
Scope: only `winner(a, b)`, not the application or a product release.
Requested contract: A if a >= 12; otherwise B if b >= 12; otherwise None.
Accepted Green receipt: 6 tests, exit code 0. Red is historical pre-implementation evidence.
Code SHA-256: `{code}`
Test SHA-256:
'''+ '\n'.join(tests)+'''

No deployment, UI, multiplayer, rollback or product-acceptance evidence is provided by this rehearsal.
This report does not certify those capabilities or homologation.
'''

def verify(root,task):
    path=Path(root)/'DELIVERY_NOTES.md'
    if not path.is_file() or path.is_symlink() or path.read_text()!=render(root,task):
        raise ValueError('documentation contains missing, altered or unsupported claims')
    return dict(valid=True,scope='score_function_only',deployment_evidence=False)

def scoped_parts():
    """Do not load SOUL, memories, user profile or project context for this run."""
    from product_boundary import scoped_parts as product_parts
    scoped=product_parts()
    if scoped:return scoped
    from planning_flow import scoped_parts as planning_parts
    scoped=planning_parts()
    if scoped: return scoped
    from e2e_boundary import scoped_parts as e2e_parts
    scoped=e2e_parts()
    if scoped: return scoped
    task=os.environ.get('HERMES_KANBAN_TASK'); database=os.environ.get('HERMES_KANBAN_DB')
    if not task or not database: return None
    path=Path(database).parent/'validation-contracts.json'
    if not path.exists(): return None
    contracts=json.loads(path.read_text())
    with closing(sqlite3.connect('file:'+database+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
        if not row: return None
        source=re.match(r'(?:INCIDENT|SPIKE)-(t_[A-Za-z0-9]+)',row['title'])
        contract=contracts.get(source[1] if source else task,{})
        if not contract.get('semantic_docs'): return None
        from review_boundary import context
        instruction=context(db,task)
        return dict(stable='''You are an isolated validation worker, not a product-delivery agent.
Use only actual tool results as evidence. The task is a tiny score function, not a game or released product.
Never claim UI, deployment, health checks, rollback, or product acceptance from this exercise.
Do not access profile memories, product repositories, credentials, configuration or external services.
Respect the persistent execution mode and tool restrictions. Never bypass a denied operation.
End after a successful terminal handoff; do not keep calling tools on a closed claim.
Documentation claims must be this JSON only: '''+json.dumps(CLAIMS),
            context=f'Current profile: {row["assignee"]}.\n{instruction}',volatile='')
