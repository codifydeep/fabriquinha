from pathlib import Path
path=Path('/opt/hermes/toolsets.py'); text=path.read_text()
anchor='"review_probe_write", "rework_document",'
assert text.count(anchor)==2
text=text.replace(anchor,anchor+' "planning_read", "planning_write", "planning_patch", "e2e_status", "e2e_write", "e2e_test", "e2e_submit", "e2e_merge", "e2e_deploy", "e2e_verify", "e2e_review_validate",')
text=text.replace(anchor,anchor+' "product_status", "product_read", "product_edit", "product_test", "product_submit", "product_inspect", "product_review_test", "product_verdict",')
path.write_text(text)
path=Path('/opt/hermes/tools/kanban_tools.py')
text=path.read_text()+'\nfrom e2e_boundary import register as register_e2e_tools\nregister_e2e_tools(registry, _check_kanban_mode)\n'
text+='\nfrom product_boundary import register as register_product_tools\nregister_product_tools(registry, _check_kanban_mode)\n'
path.write_text(text)
