"""Extract executed Red/Green receipts, never claims from prose or reasoning."""
import hashlib
import re


def collect(messages, command):
    calls, receipts = {}, []
    for item in sorted(messages, key=lambda m: (m.get('_run_order', 0), m.get('seq', 0))):
        if item.get('tool') != 'terminal':
            continue
        identity = (item.get('task_id'), item.get('call_id'))
        if item.get('type') == 'tool_use':
            raw = item.get('input') or {}
            text = raw.get('command', raw.get('text', '')).removeprefix('$ ').strip()
            if text == command:
                calls[identity] = item.get('seq')
        elif item.get('type') == 'tool_result' and identity in calls:
            output = item.get('output')
            if not isinstance(output, str):
                continue
            exit_codes = re.findall(r'\*\*exit_code:\*\*\s*(-?\d+)', output)
            if len(exit_codes) != 1:
                continue
            code = int(exit_codes[0])
            phase = None
            if code != 0 and re.search(r'(?m)^(?:(?:FAIL|ERROR): test_|FAILED \((?:failures|errors)=|not ok \d+)', output):
                phase = 'red'
            if code == 0 and re.search(r'(?m)^OK\s*$', output) and re.search(r'Ran \d+ tests? in ', output):
                phase = 'green'
            if (code == 0 and re.search(r'(?m)^# pass [1-9][0-9]*\s*$', output)
                    and re.search(r'(?m)^# fail 0\s*$', output)
                    and not re.search(r'(?m)^# (?:skipped|todo) [1-9]', output)):
                phase = 'green'
            if phase:
                receipts.append({'task_id': identity[0], 'call_id': identity[1],
                    'seq': item['seq'], 'phase': phase, 'exit_code': code,
                    'output_sha256': hashlib.sha256(output.encode()).hexdigest()})
    red = next((i for i,r in enumerate(receipts) if r['phase'] == 'red'), None)
    green = next((r for i,r in enumerate(receipts) if red is not None and i > red and r['phase'] == 'green'), None)
    if red is None or green is None:
        raise ValueError('tdd_evidence_missing: exact executed Red then Green required; never replay Red over delivered code')
    return {'red': receipts[red], 'green': green,
            'command_sha256': hashlib.sha256(command.encode()).hexdigest()}
