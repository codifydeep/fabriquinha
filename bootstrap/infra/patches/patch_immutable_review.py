from pathlib import Path

def replace(path,anchor,replacement):
    text=path.read_text()
    if replacement in text: return
    if text.count(anchor)!=1: raise ValueError('immutable-review patch anchor mismatch: '+str(path))
    path.write_text(text.replace(anchor,replacement))

root=Path('/opt/hermes')
anchor='    reason = str(redact_review_value(reason or "")).strip()\n'
replace(root/'hermes_cli/kanban_db.py',anchor,'''    from review_boundary import require_changes_evidence
    verified_reason = require_changes_evidence(conn, task_id, reason)
    if verified_reason is not None: reason = verified_reason
'''+anchor)
anchor='        entry = self.get_entry(name, scope=scope)\n'
replace(root/'tools/registry.py',anchor,'''        from review_boundary import intercept
        boundary_result = intercept(name, args)
        if boundary_result is not None:
            return json.dumps(boundary_result)
'''+anchor)
anchor='    # Coerce string arguments to their schema-declared types (e.g. "42"→42)\n'
replace(root/'model_tools.py',anchor,'''    from review_boundary import intercept
    boundary_result = intercept(function_name, function_args or {})
    if boundary_result is not None:
        return json.dumps(boundary_result)
'''+anchor)
anchor='        assignee_sql = ", assignee = ?"\n'
replace(root/'hermes_cli/kanban_db.py',anchor,'''        from review_boundary import freeze
        frozen = freeze(conn, task_id, reviewer)
        if frozen:
            metadata = dict(metadata or {}, immutable_delivery=frozen)
'''+anchor)
anchor='    # Gate: verify created_cards BEFORE the main write txn.'
replace(root/'hermes_cli/kanban_db.py',anchor,'''    from review_boundary import approve
    review_approval = approve(conn, task_id)
    if review_approval:
        metadata = dict(metadata or {}, immutable_review=review_approval)
        result = review_approval.get('summary', result)
'''+anchor)
anchor='    # Single clock reading shared by every relative-age stamp below, so all\n'
replace(root/'hermes_cli/kanban_db.py',anchor,'''    from review_boundary import context as review_context
    scoped_context = review_context(conn, task_id)
    if scoped_context:
        return scoped_context
'''+anchor)
path=root/'tools/kanban_tools.py'
text=path.read_text()
append='\nfrom review_boundary import register as register_review_tools\nregister_review_tools(registry, _check_kanban_mode)\n'
if append not in text: path.write_text(text+append)
