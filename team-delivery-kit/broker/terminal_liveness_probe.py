"""Fixed offline probe; its result never grants delivery or test-revision authority."""
import hashlib
import json
import os
import signal
import sys
import time

COMMAND = 'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1'


def main():
    sys.path.insert(0, '/opt/hermes')
    # This process has no network, model credentials, controller token or socket.
    # The callback grants only the pinned suite, not arbitrary approvals.
    from tools.terminal_tool import terminal_tool, set_approval_callback
    def deadline(*_):
        raise TimeoutError('fixed offline terminal probe deadline')
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(45)
    set_approval_callback(lambda command, *a, **kw: 'once' if command == COMMAND else 'deny')
    started = time.monotonic()
    try:
        raw = terminal_tool(command=COMMAND, timeout=30, workdir='/workspace')
        result = json.loads(raw)
        output = result.get('output') or ''
        print(json.dumps({'scope': 'diagnostic_only_not_green',
            'duration_seconds': round(time.monotonic()-started, 3),
            'exit_code': result.get('exit_code'),
            'status': result.get('status'), 'error_present': bool(result.get('error')),
            'output_sha256': hashlib.sha256(output.encode()).hexdigest(),
            'output_bytes': len(output.encode())}), flush=True)
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
