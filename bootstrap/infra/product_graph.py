"""Fail-closed structural proposal audit. Never creates cards or enables dispatch."""
import re
from planning_corrections import validate

def audit(content):
    validate(dict(role='plan',correction_gate=True),content)
    nodes={}
    for line in content.splitlines():
        match=re.match(r'^\s*- \*\*(TDD-\d{2})\*\*.*?\|\s*([a-z_]+)\s*→\s*([a-z_]+)\s*\|\s*(?:depende de|depends on):\s*([^|]+)\|\s*(?:verificação|verification):\s*(.+)',line)
        if match:
            key,owner,reviewer,deps,evidence=match.groups()
            nodes[key]=dict(owner=owner,reviewer=reviewer,parents=sorted(set(re.findall(r'TDD-\d{2}',deps))),evidence=evidence)
    if len(nodes)!=21: raise ValueError('21 actionable nodes with evidence required')
    coverage={}
    for line in content.splitlines():
        match=re.match(r'^\| (LOB-\d{2}) \| ([^|]+) \|',line)
        if match:
            if match[1] in coverage: raise ValueError('duplicate acceptance criterion')
            coverage[match[1]]=sorted(set(re.findall(r'TDD-\d{2}',match[2])))
    if set(coverage)!={f'LOB-{i:02d}' for i in range(1,8)}: raise ValueError('all lobby criteria require coverage')
    if any(not ids or not set(ids)<=nodes.keys() for ids in coverage.values()): raise ValueError('unknown or missing acceptance task')
    continuation=set(re.findall(r'^\| (V01-\d{2}) \|',content,re.M))
    if continuation!={f'V01-{i:02d}' for i in range(1,11)}: raise ValueError('full release continuation required')
    pending=set(nodes);done=set();layers=[]
    while pending:
        layer=sorted(t for t in pending if set(nodes[t]['parents'])<=done)
        if not layer:raise ValueError('cycle or unknown dependency')
        layers.append(layer);pending.difference_update(layer);done.update(layer)
    return dict(passed=True,scope='proposal_structure_only',nodes=nodes,coverage=coverage,topological_layers=layers,
        full_release_criteria=sorted(continuation),max_workers=2,max_per_profile=1,
        independent_semantic_review_required=True,native_cards_created=False,implementation_allowed=False)
