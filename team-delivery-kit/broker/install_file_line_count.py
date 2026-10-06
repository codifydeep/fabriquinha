"""Repair pinned Hermes shell reads for a final line without LF, fail closed."""
from pathlib import Path

COUNT = '''        # Get total line count
        wc_cmd = f"wc -l < {self._escape_shell_arg(path)}"
        wc_result = self._exec(wc_cmd)
        wc_output = _strip_terminal_fence_leaks(wc_result.stdout)
        try:
            total_lines = int(wc_output.strip())
        except ValueError:
            total_lines = 0
'''
FIXED = '''        # Get logical line count, not only newline count (delivery-kit EOF guard).
        wc_cmd = f"wc -l < {self._escape_shell_arg(path)}"
        wc_result = self._exec(wc_cmd)
        wc_output = _strip_terminal_fence_leaks(wc_result.stdout)
        try:
            total_lines = int(wc_output.strip())
        except ValueError:
            return ReadResult(error="Cannot verify file line count.")
        if wc_result.exit_code != 0 or total_lines < 0:
            return ReadResult(error="Cannot verify file line count.")
        unterminated_final_line = False
        if file_size > 0:
            tail_cmd = f"tail -c 1 {self._escape_shell_arg(path)} | wc -l"
            tail_result = self._exec(tail_cmd)
            tail_output = _strip_terminal_fence_leaks(tail_result.stdout).strip()
            if tail_result.exit_code != 0 or tail_output not in ("0", "1"):
                return ReadResult(error="Cannot verify file EOF.")
            unterminated_final_line = tail_output == "0"
            total_lines += int(unterminated_final_line)
'''
TAIL = '''        if not truncated and read_output.endswith('\\n'):
            tail_cmd = f"tail -c 1 {self._escape_shell_arg(path)} | wc -l"
            tail_result = self._exec(tail_cmd)
            tail_output = _strip_terminal_fence_leaks(tail_result.stdout)
            if tail_result.exit_code == 0 and tail_output.strip() == "0":
                read_output = read_output[:-1]
'''
FIXED_TAIL = '''        if not truncated and read_output.endswith('\\n') and unterminated_final_line:
            read_output = read_output[:-1]
'''


def adapt(source):
    if source.count(COUNT)!=1 or source.count(TAIL)!=1 or FIXED in source:
        raise ValueError('pinned Hermes file reader changed')
    result=source.replace(COUNT,FIXED).replace(TAIL,FIXED_TAIL)
    compile(result,'<verified-logical-line-reader>','exec')
    return result


if __name__=='__main__':
    target=Path('/opt/hermes/tools/file_operations.py')
    if target.is_symlink():raise ValueError('unexpected reader source symlink')
    target.write_text(adapt(target.read_text()))
