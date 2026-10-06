"""Arm one reviewer handoff for the next author completion, never reuse a spent wakeup."""


def ensure_review_wakeup(cli, issue_id, author_id, reviewer_id, instruction):
    matches = [item for item in cli('wakeup', 'list', issue_id)
               if item.get('agent_id') == reviewer_id
               and item.get('event_types') == ['task.completed']
               and item.get('filter_agent_id') == author_id
               and item.get('filter_task_id') is None]
    active = [item for item in matches if item.get('enabled') is True]
    if len(active) > 1:
        raise ValueError('duplicate active reviewer wakeups')
    if active:
        if active[0].get('instruction') != instruction:
            raise ValueError('active reviewer instruction drift')
        return active[0]
    return cli('wakeup', 'create', issue_id, '--agent-id', reviewer_id,
               '--event', 'task.completed', '--filter-agent-id', author_id,
               '--mode', 'once', '--instruction', instruction)
