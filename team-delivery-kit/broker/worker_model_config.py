"""Install fixed non-secret model routing in an isolated worker, then start ACP."""
import os
from pathlib import Path
import tempfile
from model_policy import MODEL, PREVIOUS_MODEL, PROXY_BASE_URL, execution_base_url

LEGACY_EXPECTED = ("model:\n"
            "  provider: openrouter\n"
            f"  default: {MODEL}\n"
            f"  base_url: {PROXY_BASE_URL}\n")
LOW_REASONING_EXPECTED = LEGACY_EXPECTED + "agent:\n  reasoning_effort: low\n"
PREVIOUS_EXPECTED = (LEGACY_EXPECTED + "  max_tokens: 8192\n"
            "agent:\n  reasoning_effort: low\n")
COMPLETE_READ_EXPECTED = (PREVIOUS_EXPECTED + "file_read_max_chars: 65536\n"
            "tool_output:\n  max_line_length: 65536\n")
EXPECTED = COMPLETE_READ_EXPECTED.replace("  reasoning_effort: low\n",
            "  reasoning_effort: low\n  api_max_retries: 1\n")


def install_config(home, execution_id=None):
    expected = EXPECTED.replace(PROXY_BASE_URL, execution_base_url(execution_id)) if execution_id else EXPECTED
    target = home / 'config.yaml'
    if target.is_symlink():
        raise ValueError('worker model configuration drift')
    if target.exists():
        current = target.read_text()
        if current == expected:
            return
        import re
        normalized = re.sub(re.escape(PROXY_BASE_URL.replace('/api/v1', '/executions/'))
                            + r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}/api/v1', PROXY_BASE_URL, current)
        accepted = (LEGACY_EXPECTED, LOW_REASONING_EXPECTED, PREVIOUS_EXPECTED,
                    COMPLETE_READ_EXPECTED, EXPECTED)
        previous = tuple(value.replace('  default: '+MODEL+'\n',
                                      '  default: '+PREVIOUS_MODEL+'\n') for value in accepted)
        if normalized not in accepted + previous:
            raise ValueError('worker model configuration drift')
        descriptor, temporary = tempfile.mkstemp(prefix='.config-migrate-', dir=home)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                stream.write(expected)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        stream.write(expected)


def main():
    home = Path(os.environ['HERMES_HOME'])
    if str(home) not in ('/session-state', '/tmp/hermes'):
        raise ValueError('unexpected Hermes home')
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    install_config(home, os.environ.get('DELIVERY_MODEL_EXECUTION_ID'))
    os.execvp('hermes', ['hermes', 'acp'])


if __name__ == '__main__':
    main()
