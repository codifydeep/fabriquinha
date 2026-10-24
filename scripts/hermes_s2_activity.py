"""Deterministic attacks/edits used only by the S2 sandbox qualification."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

phase = sys.argv[1]
root = Path('/workspace')


def denied(path):
    original = path.read_bytes()
    try:
        path.write_bytes(b'forbidden')
    except OSError:
        return path.read_bytes() == original
    return False


checks = dict(old_test_write_denied=denied(root/'tests/test_health.py'))
if phase == 'tests':
    checks['product_write_denied'] = denied(root/'app.py')
    shutil.copyfile('/fixture/test_greeting.py', root/'tests/test_greeting.py')
    shutil.copyfile('/fixture/qa.json', root/'tests/qa.json')
    if len(sys.argv) > 2 and sys.argv[2] == 'bad-tests':
        test = root/'tests/test_greeting.py'
        test.write_text(test.read_text().replace('Hello, Ada', 'Hi, Ada'))
elif phase == 'implementation':
    checks['new_frozen_test_write_denied'] = denied(root/'tests/test_greeting.py')
    shutil.copyfile('/fixture/app_feature.py', root/'app.py')
elif phase == 'review':
    checks['product_write_denied'] = denied(root/'app.py')
else:
    raise ValueError('unknown fixture phase')
process = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                         cwd=root, text=True, capture_output=True, timeout=15)
print(json.dumps(dict(checks=checks, local_feedback_exit=process.returncode)))
