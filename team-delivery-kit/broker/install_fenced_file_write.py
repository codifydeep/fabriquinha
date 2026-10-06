"""Build-time adaptation; preserve Hermes guards and patch logic."""
from pathlib import Path

target = Path('/opt/hermes/tools/file_operations.py')
source = target.read_text()
anchor = '        q_path = self._escape_shell_arg(path)\n        parent = os.path.dirname(path) or "."\n'
if source.count(anchor) != 1:
    raise ValueError('pinned Hermes atomic-write implementation changed')
replacement = ('        q_path = self._escape_shell_arg(path)\n'
               '        if os.environ.get("HERMES_FENCED_INPLACE_WRITES") == "1":\n'
               '            return self._exec("python3 /fenced_file_write.py " + q_path, stdin_data=content)\n'
               '        parent = os.path.dirname(path) or "."\n')
target.write_text(source.replace(anchor, replacement))
