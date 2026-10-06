"""Targeted consistency checks for PR19 corrections; semantic review still required."""
import re
import hashlib
from review_policy import validate_review


def validate(card,content):
    if not card.get('correction_gate'): return dict(required=False)
    if card.get('exact_content_sha256') and hashlib.sha256(content.encode()).hexdigest()!=card['exact_content_sha256']:
        raise ValueError('editorial_scope: apply only the registered exact replacements; preserve every other byte of the approved document.')
    role=card['role']
    if role=='design':
        match=re.search(r'BRIEF-TRUCO-v0\.1-R1-\d+',content)
        if not match or match[0]!='BRIEF-TRUCO-v0.1-R1-20260916':
            line=content[:match.start()].count('\n')+1 if match else 1
            raise ValueError(f'brief_reference line {line}: primary identifier must be BRIEF-TRUCO-v0.1-R1-20260916; found '+(match[0] if match else 'missing'))
    if role=='architecture':
        d1=re.search(r'### D1\b.*?(?=### D2\b|\Z)',content,re.S)
        if d1 and '(D6)' in d1[0]:
            raise ValueError('cross_reference D1: reconnection reference (D6) must be (D7); D6 covers room concurrency.')
        if re.search(r'^### D8[^\n]*seixo',content,re.M):
            raise ValueError('heading D8: replace seixo with rendering layer/strategy. Historical quotes are allowed.')
    if role=='plan':
        graph={}
        for line in content.splitlines():
            if not re.match(r'^\s*- \*\*TDD-\d{2}\*\*',line): continue
            match=re.match(r'^\s*- \*\*(TDD-\d{2})\*\*.*?\|\s*([a-z_]+)\s*→\s*([a-z_]+)\s*\|\s*(?:depende de|depends on):\s*([^|]+)\|',line)
            if not match: raise ValueError('task_format: use - **TDD-XX** — title | canonical_owner → canonical_reviewer | depends on: TDD-YY or — | verification: ...')
            tid,author,reviewer,parents=match.groups()
            if tid in graph: raise ValueError('Duplicate TDD task: '+tid)
            error=validate_review(author,reviewer)
            if error: raise ValueError(tid+': '+error)
            graph[tid]=set(re.findall(r'TDD-\d{2}',parents))
        if set(graph)!={f'TDD-{i:02d}' for i in range(1,22)}:
            raise ValueError('Preserve all 21 TDD IDs in the explicit task format; no silent scope deletion.')
        pending=dict(graph); done=set()
        while pending:
            ready={tid for tid,parents in pending.items() if parents<=done}
            if not ready: raise ValueError('Cycle or unknown dependency in TDD graph.')
            done.update(ready)
            for tid in ready: del pending[tid]
    return dict(passed=True,scope='targeted_document_consistency',semantic_review_required=True)
