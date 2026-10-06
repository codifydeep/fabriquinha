"""Controller-only C10 phase gates. Partial progress never grants author authority."""
import hashlib
import re
try:
    import maintenance_snapshot_validate as snapshots
    import suite_failure
except ImportError:
    from broker import maintenance_snapshot_validate as snapshots, suite_failure

QUERY_LINES = (512, 515, 528, 531)
C10 = 'test_c10_stale_query_and_status_responses_are_discarded'
SCHEMA = 'c10-query-status-checkpoints-v1'


def admission(state):
    phase=state.get('c10_checkpoints',{}).get('phase')
    if phase=='QUERY':
        try:import c10_query_admission as selected
        except ImportError:from broker import c10_query_admission as selected
    elif phase=='STATUS':
        try:import c10_status_admission as selected
        except ImportError:from broker import c10_status_admission as selected
    else:raise ValueError('explicit phase-specific admission required')
    return selected


def sha(content):
    return hashlib.sha256(content).hexdigest()


def query_candidate(seed):
    """An exact transformation used for comparison, NEVER applied by controller."""
    lines = seed.splitlines(keepends=True)
    if len(lines) < 554:
        raise ValueError('complete frozen driver required')
    for number in QUERY_LINES:
        old = lines[number - 1]
        match = re.fullmatch(rb'(\s*resolve(?:Newest|Oldest)\()(?P<array>\[.*\])(\);\r?\n)', old)
        if not match:
            raise ValueError('exact existing bare-array response anchor required')
        lines[number - 1] = match[1] + b'{items:' + match['array'] + b'}' + match[3]
    return b''.join(lines)


def verify_bytes(phase, seed, candidate):
    if not isinstance(seed, bytes) or not isinstance(candidate, bytes) or len(candidate) > 32768:
        raise ValueError('bounded frozen bytes required')
    if phase == 'QUERY':
        query_candidate(seed)  # Validate all four immutable bare-array anchors.
        before,after=seed.splitlines(keepends=True),candidate.splitlines(keepends=True)
        if len(before)!=len(after):raise ValueError('QUERY must preserve absolute line boundaries')
        for number,(old,new) in enumerate(zip(before,after),1):
            if number not in QUERY_LINES:
                if old!=new:raise ValueError('QUERY changed outside its four envelopes')
                continue
            match=re.fullmatch(rb'(\s*resolve(?:Newest|Oldest)\()(?P<array>\[.*\])(\);\r?\n)',old)
            # Only spaces/tabs INSIDE the inserted object envelope are variable.
            # Fixture array bytes, call prefix, suffix and every other line remain exact.
            pattern=(re.escape(match[1])+rb'\{[ \t]*items[ \t]*:[ \t]*'+
                re.escape(match['array'])+rb'[ \t]*\}'+re.escape(match[3]))
            if not re.fullmatch(pattern,new):raise ValueError('QUERY permits only four fixture-preserving items envelopes')
    elif phase == 'STATUS':
        lines = seed.splitlines(keepends=True)
        if len(lines) < 554 or b'C10STATUS - placeholder checkpoint' not in lines[533]:
            raise ValueError('exact QUERY output with original STATUS placeholder required')
        snapshots.preserve_line_window(seed, candidate, start=534, end=536)
        if candidate == seed:
            raise ValueError('STATUS must change its placeholder')
        # QUERY must already be enveloped, not repaired as part of STATUS.
        for number in QUERY_LINES:
            if not re.search(rb'\(\{[ \t]*items[ \t]*:[ \t]*\[',lines[number - 1]):
                raise ValueError('verified QUERY envelope seed required')
    else:
        raise ValueError('explicit QUERY or STATUS phase required')
    return {'schema': SCHEMA, 'phase': phase, 'seed_test_sha256': sha(seed),
            'test_sha256': sha(candidate), 'scope_verified': True,
            'delivery_approval': False}


def verify_snapshot(seed, candidate, expected_seed, expected_manifest, phase):
    from pathlib import Path
    seed, candidate = Path(seed), Path(candidate)
    _, old = snapshots.manifest(seed)
    raw, current = snapshots.manifest(candidate)
    if (old[snapshots.TEST]['sha256'] != expected_seed or sha(raw) != expected_manifest
            or set(old) != set(current) or any(old[n] != current[n] for n in old if n != snapshots.TEST)):
        raise ValueError('exact unchanged product and frozen phase identities required')
    proof = verify_bytes(phase, snapshots.product.regular_within(seed, snapshots.TEST),
                         snapshots.product.regular_within(candidate, snapshots.TEST))
    return dict(proof, manifest_sha256=expected_manifest)


def phase_state(state, phase):
    checkpoint = state.get('c10_checkpoints', {})
    proof = checkpoint.get('scope_receipt', {})
    if (checkpoint.get('schema') != SCHEMA or checkpoint.get('phase') != phase
            or proof.get('schema') != SCHEMA or proof.get('phase') != phase
            or proof.get('scope_verified') is not True or proof.get('delivery_approval') is not False
            or proof.get('seed_test_sha256') != checkpoint.get('seed', {}).get('validation', {}).get('test_sha256')
            or proof.get('test_sha256') != state['validation']['test_sha256']
            or proof.get('manifest_sha256') != state['validation']['manifest_sha256']):
        raise ValueError('controller-verified exact phase snapshot required')
    return checkpoint


def partial_receipt(state, failure, output):
    checkpoint = phase_state(state, 'QUERY')
    actual = suite_failure.evidence(1, output, state['author_task'], state['snapshot']['volume'])
    core=dict(failure)
    if 'diagnostic_read_files' in core:
        diagnostics=core.pop('diagnostic_read_files')
        if diagnostics!=['app/static/app.js','app/static/index.html','tests/test_incremental_u3.py']:
            raise ValueError('exact runner readonly diagnostic metadata required')
    if (core != actual or actual['category'] != 'executed_test_failure'
            or actual['tests_executed'] != 259 or actual['exception_types'] != ['KeyError']
            or len(actual['failures']) != 1 or actual['failures'][0]['kind'] != 'ERROR'
            or actual['failures'][0]['test'] != C10
            or re.findall(r"(?m)^KeyError: '([^']+)'$", output) != ['status_genA_urls']
            or re.findall(r'(?m)^Ran (\d+) tests?\b', output) != ['259']
            or re.findall(r'(?m)^FAILED \(([^)]+)\)$', output) != ['errors=1']):
        raise ValueError('full259 suite with ONLY expected missing STATUS error required')
    return {'schema': SCHEMA, 'phase': 'QUERY', 'result': 'PARTIAL',
            'source_task': state['author_task'], 'snapshot': state['snapshot'],
            'validation': state['validation'], 'scope_receipt': checkpoint['scope_receipt'],
            'full_suite_failure': failure, 'c09_status': 'passed_in_actual_full_suite',
            'green': False, 'author_scope_authorized': False, 'delivery_approval': False}


def final_receipt(state, full_green, output):
    checkpoint = phase_state(state, 'STATUS')
    partial = checkpoint.get('query_receipt', {})
    seed = checkpoint['seed']
    if (partial.get('schema') != SCHEMA or partial.get('phase') != 'QUERY'
            or partial.get('result') != 'PARTIAL' or partial.get('green') is not False
            or partial.get('delivery_approval') is not False or partial.get('author_scope_authorized') is not False
            or partial.get('source_task') != seed.get('task_id') or partial.get('snapshot') != seed.get('snapshot')
            or partial.get('validation') != seed.get('validation')
            or full_green.get('source_task') != state['author_task']
            or full_green.get('volume') != state['snapshot']['volume']
            or full_green.get('manifest_sha256') != state['validation']['manifest_sha256']
            or full_green.get('test_sha256') != state['validation']['test_sha256']
            or full_green.get('tests') != 259 or full_green.get('exit_code') != 0
            or full_green.get('network') != 'none' or full_green.get('snapshot_mount') != 'readonly'
            or full_green.get('executed_by') != 'controller_maintenance_full_suite'
            or full_green.get('delivery_approval') is not False
            or not isinstance(output,str) or sha(output.encode())!=full_green.get('output_sha256')
            or re.findall(r'(?m)^Ran (\d+) tests?\b',output)!=['259']
            or re.findall(r'(?m)^(OK(?: \([^)]*\))?|FAILED \([^)]*\))$',output)!=['OK']
            or re.search(r'(?m)^(FAIL|ERROR):',output)):
        raise ValueError('exact QUERY lineage and full259 STATUS Green required')
    return {'schema': SCHEMA, 'phase': 'STATUS', 'result': 'AWAITING_INDEPENDENT_REVIEW',
            'source_task': state['author_task'], 'snapshot': state['snapshot'],
            'validation': state['validation'], 'query_receipt': partial,
            'full_suite': full_green, 'author_scope_authorized': False, 'delivery_approval': False}


def require_review_ready(state):
    checkpoint=phase_state(state,'STATUS');final=checkpoint.get('final_receipt',{})
    if (final.get('schema')!=SCHEMA or final.get('phase')!='STATUS'
            or final.get('result')!='AWAITING_INDEPENDENT_REVIEW'
            or final.get('source_task')!=state['author_task'] or final.get('snapshot')!=state['snapshot']
            or final.get('validation')!=state['validation']
            or final.get('full_suite')!=state.get('suite_receipt')
            or final.get('query_receipt')!=checkpoint.get('query_receipt')
            or final.get('delivery_approval') is not False):
        raise ValueError('exact final STATUS Green required before independent review')
