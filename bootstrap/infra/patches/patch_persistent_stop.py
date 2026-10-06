from pathlib import Path
path=Path('/opt/hermes/agent/kanban_stop.py')
text=path.read_text()
anchor='    if not kanban_stop_nudge_enabled():\n'
assert text.count(anchor)==1
text=text.replace(anchor,'    from persistent_stop import build_nudge\n    return build_nudge(messages=messages, attempts=attempts, max_attempts=max_attempts, task_id=task_id)\n\n'+anchor)
path.write_text(text)
path=Path('/opt/hermes/agent/conversation_loop.py')
text=path.read_text()
text=text.replace('kanban_complete/kanban_block — nudging to finish','durable terminal transition — checking execution mode')
anchor='    while (api_call_count < agent.max_iterations and agent.iteration_budget.remaining > 0) or agent._budget_grace_call:\n'
assert text.count(anchor)==1
text=text.replace(anchor,anchor+'''        from persistent_stop import closed_execution_message
        _kanban_closed = closed_execution_message()
        if _kanban_closed:
            final_response = _kanban_closed
            _turn_exit_reason = "kanban_execution_closed"
            break
''')
path.write_text(text)
