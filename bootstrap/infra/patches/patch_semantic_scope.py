from pathlib import Path
path=Path('/opt/hermes/agent/system_prompt.py')
text=path.read_text()
anchor='    # Local import to avoid pulling model_tools at module load.  Tests\n'
addition='''    from semantic_delivery import scoped_parts
    rehearsal_parts = scoped_parts()
    if rehearsal_parts is not None:
        return rehearsal_parts
'''+anchor
if addition not in text:
    assert text.count(anchor)==1
    path.write_text(text.replace(anchor,addition))
