"""Controller-derived capture witnesses and a fail-closed diagnostic contract."""
import hashlib
import json
import ast

try:
    import test_capture_constraints
    import test_review_report
except ImportError:
    from broker import test_capture_constraints, test_review_report

MARKER = 'DELIVERY_CAPTURE_CONSTRAINTS_V1'


def load(broker, issue):
    with broker.db() as con:
        row = con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?', (issue,)).fetchone()
    if not row:
        return None
    red = json.loads(row[0])['red']
    report = test_review_report.load(broker, issue, red['manifest_sha256'])
    witnesses = []
    sources = {}
    for path, expected in red['test_sha256'].items():
        file = report['candidate']['files'][path]
        text = '\n'.join(file['lines'])
        if (file['sha256'] != expected or not any(
                hashlib.sha256(value.encode()).hexdigest() == expected for value in (text, text + '\n'))):
            raise ValueError('capture source hash drift')
        sources[path] = file['lines']
        for witness in test_capture_constraints.inspect(text):
            witnesses.append({'path': path, **witness})
    if len(witnesses) > 3:
        raise ValueError('capture witness budget exceeded; split diagnostic')
    return {'issue_id': issue, 'manifest_sha256': red['manifest_sha256'],
            'test_sha256': red['test_sha256'], 'witnesses': witnesses, 'sources': sources}


def summary(report):
    result = [{'path': w['path'], 'capture': w['capture'],
             'whole_line': w['whole']['line'], 'whole_expected': w['whole']['expected'],
             'element_line': w['element']['line'], 'index': w['element']['index'],
             'element_expected': w['element']['expected'], 'implied_element': w['implied_element']}
            for w in report['witnesses']]
    for item in result:
        lines = report.get('sources', {}).get(item['path'], [])
        anchors = []
        if lines:
            for node in ast.walk(ast.parse('\n'.join(lines))):
                if (isinstance(node, ast.Return) and isinstance(node.value, ast.Subscript)
                        and isinstance(node.value.value, ast.Subscript)
                        and isinstance(node.value.value.value, ast.Attribute)
                        and node.value.value.value.attr == 'report'):
                    anchors.append({'line': node.lineno, 'quote': lines[node.lineno - 1].strip()})
                elif (isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute)
                      and t.attr == 'report' for t in node.targets)):
                    anchors.append({'line': node.lineno, 'quote': lines[node.lineno - 1].strip()})
        item['source_anchors'] = sorted(anchors, key=lambda anchor: anchor['line'])[:3]
    return result


def validate(decision, report, reads):
    resolutions = decision.get('capture_resolutions')
    if not isinstance(resolutions, list) or len(resolutions) != len(report['witnesses']):
        raise ValueError('every capture witness requires a resolution')
    paths = {'/evidence/candidate/' + w['path'] for w in report['witnesses']}
    if any(path not in reads or type(reads[path].get('lines')) is not int
           or reads[path]['lines'] <= 0 or reads[path]['lines'] != reads[path].get('total_lines') for path in paths):
        raise ValueError('capture diagnosis lacks complete source inspection')
    seen = set()
    shared = True
    for resolution in resolutions:
        fields = {'path', 'capture', 'whole_line', 'element_line', 'lifetime', 'line', 'quote'}
        if not isinstance(resolution, dict) or set(resolution) != fields:
            raise ValueError('exact capture resolution fields required')
        identity = tuple(resolution[k] for k in ('path', 'capture', 'whole_line', 'element_line'))
        expected = {tuple((w['path'], w['capture'], w['whole']['line'], w['element']['line']))
                    for w in report['witnesses']}
        if identity not in expected or identity in seen:
            raise ValueError('capture resolution identity drift')
        seen.add(identity)
        line, quote = resolution['line'], resolution['quote']
        source = report['sources'][resolution['path']]
        if (type(line) is not int or not 1 <= line <= len(source)
                or not isinstance(quote, str) or not 1 <= len(quote) <= 300
                or not quote.strip() or quote not in source[line - 1]):
            raise ValueError('capture lifetime quote not present in source')
        if resolution['lifetime'] not in ('shared', 'unknown'):
            raise ValueError('unproven distinct capture requires a separate experiment')
        shared &= resolution['lifetime'] == 'shared'
    action = decision['action']
    if action == 'request_correction' or (action == 'request_test_revision' and not shared):
        raise ValueError('product correction cannot resolve an unresolved capture contradiction')
    if action not in ('request_test_revision', 'escalate_cto'):
        raise ValueError('capture diagnosis does not confer delivery authority')
    return {'read_contract': 'complete-lines-v2', 'required_read_paths': sorted(paths),
            'read_evidence': {path: reads[path] for path in sorted(paths)}}
