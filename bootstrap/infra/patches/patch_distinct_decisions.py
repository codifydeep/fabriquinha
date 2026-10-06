from pathlib import Path
TARGET=Path('/opt/hermes/hermes_cli/kanban_db.py')
ANCHOR='        same_cause = prev_kind == kind\n        recurrences = prev_recurrences + 1 if same_cause else 1\n'
BLOCK='''        same_cause = prev_kind == kind
        # Distinct, correlated human questions are not retries of one cause.
        # Preserve the native breaker for the SAME question and all ordinary
        # technical failures; only a changed decision identity resets it.
        if same_cause and kind == "needs_input":
            import re as _decision_re
            current_question = _decision_re.search(r"\\[DECISION:(q_[A-Za-z0-9_-]+)\\]", reason or "")
            previous_event = conn.execute(
                "SELECT payload FROM task_events WHERE task_id=? AND kind IN ('blocked','block_loop_detected') ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            previous_reason = json.loads(previous_event["payload"] or "{}").get("reason", "") if previous_event else ""
            previous_question = _decision_re.search(r"\\[DECISION:(q_[A-Za-z0-9_-]+)\\]", previous_reason)
            if current_question and previous_question and current_question[1] != previous_question[1]:
                same_cause = False
        recurrences = prev_recurrences + 1 if same_cause else 1
'''


def apply(source):
    if BLOCK in source:
        return source
    if source.count(ANCHOR)!=1:
        raise ValueError('unknown block recurrence entry')
    return source.replace(ANCHOR,BLOCK)


if __name__=='__main__':
    TARGET.write_text(apply(TARGET.read_text()))
