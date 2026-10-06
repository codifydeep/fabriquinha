"""Privacy-bounded tool evidence. Code containing 'error' is not a tool failure."""
import hashlib
import json
import re


def result_status(tool, output):
    if not isinstance(output, str):
        return 'unclassified'
    if tool=='surgical_test_edit' and re.search(r'(?:^|\n)(?:Error: |surgical_test_edit failed: )surgical_edit_rejected(?::[a-z_]+:[a-z_]+)?(?:\n|$)',output):
        return 'structured_failure'
    # ACP read formatting wraps arbitrary source text, including exceptions and
    # words such as TypeError. Never scan that body for failure keywords.
    if tool == 'read_file' and re.match(
            r'^Read /workspace/[A-Za-z0-9_./-]+(?: \([^\n]*\))? — \d+ total lines\n\n', output):
        return 'read_returned'
    try:
        record = json.loads(output)
    except ValueError:
        return 'unclassified'
    if not isinstance(record, dict):
        return 'unclassified'
    if record.get('error') or record.get('success') is False:
        return 'structured_failure'
    if tool == 'read_file' and isinstance(record.get('content'), str) and 'total_lines' in record:
        return 'read_returned'
    if tool in ('write_file','surgical_test_edit') and type(record.get('bytes_written')) is int and record['bytes_written'] > 0:
        return 'write_returned'
    return 'unclassified'


def summarize(messages, declared_path):
    """Counts only; no prompts, commands, result excerpts or inference of writes."""
    counts = {}
    writes = 0
    matching = 0
    unknown_arguments = 0
    for item in messages:
        tool = item.get('tool')
        if item.get('type') == 'tool_use':
            raw = item.get('input')
            if not isinstance(raw, dict) or not raw:
                unknown_arguments += 1
            if tool == 'write_file':
                writes += 1
                if isinstance(raw, dict) and raw.get('path') == declared_path:
                    matching += 1
        elif item.get('type') == 'tool_result' and tool in ('read_file', 'write_file', 'surgical_test_edit','terminal'):
            key = tool + ':' + result_status(tool, item.get('output'))
            counts[key] = counts.get(key, 0) + 1
    return {'schema': 'test-author-activity-v1', 'declared_path': declared_path,
            'message_count': len(messages), 'tool_result_counts': counts,
            'write_file_call_count': writes, 'declared_write_file_call_count': matching,
            'unrecorded_argument_count': unknown_arguments,
            'terminal_side_effects': 'not_inferred',
            'artifact_existence': 'must_be_verified_by_controller_snapshot',
            'events_sha256': hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()}
