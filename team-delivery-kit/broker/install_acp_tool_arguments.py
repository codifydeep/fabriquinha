"""Pinned ACP compatibility fix: step callbacks pass JSON strings, not dicts."""
from pathlib import Path

ANCHOR = '                    function_args = tool_info.get("arguments") or tool_info.get("args")\n'
REPLACEMENT = ANCHOR + '''                    if isinstance(function_args, str):
                        try:
                            function_args = json.loads(function_args)
                        except (ValueError, TypeError):
                            function_args = None
                    if not isinstance(function_args, dict):
                        function_args = None
'''


def adapt(source):
    if source.count(ANCHOR) != 1 or REPLACEMENT in source:
        raise ValueError('pinned ACP step callback changed')
    return source.replace(ANCHOR, REPLACEMENT)


READ_ANCHOR = '    return _truncate_text(f"{header}\\n\\n{_fenced_text(content)}")\n'
OLD_DISPLAY = '    display_limit = 131072 if path.startswith(("/evidence/candidate/", "/evidence/previous/")) else 5000\n'
NEW_DISPLAY = '    display_limit = 131072 if path.startswith(("/evidence/candidate/", "/evidence/previous/", "/delivery/")) else 5000\n'


def upgrade_tools(source):
    if source.count(OLD_DISPLAY)!=1 or NEW_DISPLAY in source:
        raise ValueError('pinned installed ACP formatter changed')
    return source.replace(OLD_DISPLAY,NEW_DISPLAY)


def adapt_tools(source):
    if source.count(READ_ANCHOR) != 1:
        raise ValueError('pinned ACP read formatter changed')
    # File tools already bound read output. Avoid the ACP UI's extra 5k
    # truncation only for controller-mounted review evidence; retain it elsewhere.
    return source.replace(READ_ANCHOR,
        NEW_DISPLAY +
        '    return _truncate_text(f"{header}\\n\\n{_fenced_text(content)}", limit=display_limit)\n')


if __name__ == '__main__':
    import sys
    if sys.argv[1:]==['--upgrade-tools-only']:
        target=Path('/opt/hermes/acp_adapter/tools.py')
        target.write_text(upgrade_tools(target.read_text()))
        sys.exit(0)
    target = Path('/opt/hermes/acp_adapter/events.py')
    target.write_text(adapt(target.read_text()))
    target = Path('/opt/hermes/acp_adapter/tools.py')
    target.write_text(adapt_tools(target.read_text()))
