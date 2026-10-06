from pathlib import Path
p=Path('/opt/hermes/hermes_cli/kanban_db.py')
s=p.read_text()
marker='        # Budget exhaustion requires diagnosis, not a blind identical retry.\n'
anchor='        if force_trip or failures >= effective_limit:\n'
if marker not in s:
    assert s.count(anchor)==1
    s=s.replace(anchor,marker+'''        if 'Iteration budget exhausted' in error:
            force_trip = True
'''+anchor)
    p.write_text(s)
