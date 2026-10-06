"""Fail-closed build adaptation for the pinned Hermes tool registry."""
from pathlib import Path


def adapt_toolsets(source):
    anchor='    "read_file", "write_file", "patch", "search_files",\n'
    lines=source.splitlines(keepends=True)
    if lines.count(anchor)!=1 or '"surgical_test_edit"' in source:raise ValueError('pinned Hermes core file toolset changed')
    index=lines.index(anchor)
    lines.insert(index+1,'    "surgical_test_edit",  # Availability is controller-grant gated.\n')
    return ''.join(lines)


def adapt_acp_toolsets(source):
    start='    "hermes-acp": {\n'
    if source.count(start)!=1:raise ValueError('pinned Hermes ACP toolset changed')
    prefix,_,rest=source.partition(start)
    section,separator,suffix=rest.partition('\n    },\n')
    anchor='            "read_file", "write_file", "patch", "search_files",\n'
    lines=section.splitlines(keepends=True)
    if not separator or lines.count(anchor)!=1 or '"surgical_test_edit"' in section:
        raise ValueError('pinned Hermes ACP file tools changed')
    lines.insert(lines.index(anchor)+1,'            "surgical_test_edit",  # Controller-grant gated.\n')
    return prefix+start+''.join(lines)+separator+suffix


def adapt(source):
    anchor = '                handler=handler,\n'
    if source.count(anchor) != 1:
        raise ValueError('pinned Hermes handler registration changed')
    source = source.replace(anchor,
        '                handler=__import__("review_tool_policy").fence(name, handler, is_async),\n')
    anchor = '        entry = self.get_entry(name, scope=scope)\n        if not entry:\n'
    if source.count(anchor) != 1:
        raise ValueError('pinned Hermes dispatch changed')
    return source.replace(anchor,
        '        policy_result = __import__("review_tool_policy").controlled(name, args)\n'
        '        if policy_result is not None:\n'
        '            return policy_result\n' + anchor)


if __name__ == '__main__':
    path = Path('/opt/hermes/tools/registry.py')
    path.write_text(adapt(path.read_text()))
    toolsets=Path('/opt/hermes/toolsets.py')
    toolsets.write_text(adapt_acp_toolsets(adapt_toolsets(toolsets.read_text())))
