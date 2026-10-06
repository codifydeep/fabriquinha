"""Idempotent registration for the pinned, already-patched base image."""
from pathlib import Path
from product_boundary import SCHEMAS
path=Path('/opt/hermes/toolsets.py');text=path.read_text()
anchor='"review_probe_write", "rework_document",'
if '"product_status"' not in text:
    assert text.count(anchor)==2
    text=text.replace(anchor,anchor+' '+', '.join('"'+n+'"' for n in SCHEMAS)+',')
    path.write_text(text)
path=Path('/opt/hermes/tools/kanban_tools.py');text=path.read_text()
if 'register_product_tools' not in text:
    path.write_text(text+'\nfrom product_boundary import register as register_product_tools\nregister_product_tools(registry, _check_kanban_mode)\n')

path=Path('/opt/hermes/hermes_cli/kanban_db.py');text=path.read_text()
old='matrix_error = validate_review(canonical_implementer, reviewer)'
new='from product_review_policy import native_error\n        matrix_error = native_error(conn, task_id, canonical_implementer, reviewer)'
if new not in text:
    if text.count(old)!=1:raise ValueError('unknown native matrix anchor')
    path.write_text(text.replace(old,new))
