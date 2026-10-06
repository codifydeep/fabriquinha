"""Observed read-tool results, never an assistant's claim of inspection."""
import hashlib
import json
import re


def observations(messages, wire=False):
    return {path: receipt for path, receipt in coverage(messages, wire).items()
            if receipt['lines'] == receipt['total_lines']}


def coverage(messages, wire=False):
    calls, found = {}, {}
    for message in messages:
        if wire and message.get('role') == 'assistant':
            for call in message.get('tool_calls') or []:
                function = call.get('function') or {}
                if function.get('name') == 'read_file':
                    try:
                        args = json.loads(function.get('arguments', '{}'))
                    except (TypeError, ValueError):
                        continue
                    if isinstance(args, dict) and isinstance(args.get('path'), str):
                        calls[call.get('id')] = (args['path'], args.get('offset', 1), args.get('limit'))
        elif not wire and message.get('type') == 'tool_use' and message.get('tool') == 'read_file':
            raw = message.get('input') or {}
            path = raw.get('path')
            if path is None:
                match = re.search(r'/(?:evidence/(?:candidate|previous)|delivery)/[A-Za-z0-9_./-]+', raw.get('text', ''))
                path = match.group(0) if match else None
            calls[message.get('call_id')] = (path, raw.get('offset', 1), raw.get('limit'))
        is_result = message.get('role') == 'tool' if wire else message.get('type') == 'tool_result'
        if not is_result:
            continue
        identifier = message.get('tool_call_id') if wire else message.get('call_id')
        if identifier not in calls:
            continue
        path, offset, limit = calls[identifier]
        output = message.get('content') if wire else message.get('output')
        if not isinstance(output, str) or message.get('output_truncated'):
            continue
        try:
            data = json.loads(output)
        except ValueError:
            # ACP starts omit input. Its actual completed read identifies the
            # path and total, followed by a fenced numbered page.
            match = re.fullmatch(r'Read (/(?:evidence/(?:candidate|previous)|delivery)/[A-Za-z0-9_./-]+)'
                                 r'(?: \(from line (\d+)(?:, limit (\d+))?\))?'
                                 r' — (\d+) total lines\n\n(`{3,})[^\n]*\n(.*)\n\5', output, re.DOTALL)
            if not match:
                continue
            actual_path, actual_offset, actual_limit, total, _, content = match.groups()
            if path and actual_path != path:
                continue
            path, offset = actual_path, int(actual_offset or 1)
            limit = int(actual_limit) if actual_limit else None
            data = {'content': content, 'total_lines': int(total)}
        if (not path or not isinstance(data, dict) or data.get('error')
                or data.get('success') is False or data.get('dedup')
                or data.get('content_returned') is False):
            continue
        content = data.get('content', '')
        if not isinstance(content, str):
            continue
        numbered = re.findall(r'^[ \t]*(\d+)\|(.*)$', content, re.MULTILINE)
        total = data.get('total_lines')
        # Pinned Hermes splits newline-terminated slices with split('\n'):
        # the last empty numbered item is a transport sentinel, not another
        # source line. Remove only the provable item beyond the page/EOF.
        end = min(total, offset + limit - 1) if type(total) is int and type(offset) is int and type(limit) is int and limit > 0 else total
        if numbered and type(end) is int and numbered[-1] == (str(end + 1), ''):
            numbered.pop()
        numbers = [int(n) for n, _ in numbered]
        if (type(total) is not int or not 0 < total <= 100000 or type(offset) is not int
                or not numbers or numbers != list(range(offset, offset + len(numbers)))
                or numbers[-1] > total):
            continue
        receipt = found.setdefault(path, {'call_id': identifier, 'total_lines': total,
                                         'line_content': {}, 'hashes': []})
        if receipt['total_lines'] != total:
            receipt['invalid'] = True
        for number, text in numbered:
            number = int(number)
            # Hermes clips individual lines while retaining their number.
            # Counting that number does not prove the source was inspected.
            if text.endswith('... [truncated]') or (data.get('truncated_by') == 'bytes'
                    and number == numbers[-1]):
                continue
            if number in receipt['line_content'] and receipt['line_content'][number] != text:
                receipt['invalid'] = True
            receipt['line_content'][number] = text
        receipt['hashes'].append(hashlib.sha256(output.encode()).hexdigest())
        receipt['call_id'] = identifier
        receipt['lines'] = len(receipt['line_content'])
        receipt['output_sha256'] = hashlib.sha256(json.dumps(receipt['hashes']).encode()).hexdigest()
    result = {}
    for path, receipt in found.items():
        if receipt.get('invalid'):
            continue
        receipt['next_offset'] = next((n for n in range(1, receipt['total_lines'] + 1)
                                       if n not in receipt['line_content']), None)
        result[path] = {k: v for k, v in receipt.items() if k not in ('line_content', 'hashes')}
    return result


def next_read(messages, path):
    receipt = coverage(messages, wire=True).get(path)
    offset = receipt['next_offset'] if receipt else 1
    attempts = 0
    total_attempts = 0
    for message in messages:
        if message.get('role') != 'assistant':
            continue
        for call in message.get('tool_calls') or []:
            function = call.get('function') or {}
            if function.get('name') != 'read_file':
                continue
            total_attempts += 1
            try:
                args = json.loads(function.get('arguments', '{}'))
            except (TypeError, ValueError):
                continue
            if isinstance(args, dict) and args.get('path') == path and args.get('offset', 1) == offset:
                attempts += 1
    if attempts >= 2 or total_attempts >= 32:
        raise ValueError('review inspection stalled')
    return offset
