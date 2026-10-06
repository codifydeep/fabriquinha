from pathlib import Path
root=Path('/opt/hermes')
path=root/'toolsets.py'
text=path.read_text()
anchor='"kanban_attach", "kanban_attach_url", "kanban_attachments",'
addition=anchor+'\n            "review_inspect", "review_validate", "review_fetch_parent", "review_diagnose", "review_resume", "review_probe_write", "rework_document",'
if addition not in text:
    assert text.count(anchor)==2,'unexpected core/kanban catalogues'
    path.write_text(text.replace(anchor,addition))
path=root/'model_tools.py'; text=path.read_text()
if 'def _unscoped_get_tool_definitions(' not in text:
    assert text.count('def get_tool_definitions(')==1
    text=text.replace('def get_tool_definitions(','def _unscoped_get_tool_definitions(',1)
    text+='''

def get_tool_definitions(enabled_toolsets=None, disabled_toolsets=None, quiet_mode=False, skip_tool_search_assembly=False):
    from review_boundary import filter_catalogue
    result = filter_catalogue(_unscoped_get_tool_definitions(enabled_toolsets, disabled_toolsets, quiet_mode, skip_tool_search_assembly))
    global _last_resolved_tool_names
    _last_resolved_tool_names = [d["function"]["name"] for d in result]
    return result
'''
    path.write_text(text)
