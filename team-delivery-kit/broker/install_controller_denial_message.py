"""Preserve denial, distinguish fixed controller policy from human refusal."""
from pathlib import Path

OLD = '''                "BLOCKED: User denied this command. The user has NOT consented "
                "to this action. Do NOT retry this command, do NOT rephrase "
                "it, and do NOT attempt the same outcome via a different "
                "command. Stop the current workflow and wait for the user "
                f"to respond before taking any further destructive or "
                f"irreversible action.{breaker_addendum}"
'''
NEW = '''                (
                    "BLOCKED: The fixed controller policy denied this command. "
                    "Do NOT retry, rephrase or work around this denied operation. "
                    "This is not a human revocation of all task authority. "
                    "You may continue unrelated already-permitted work using the "
                    "declared file tools and the exact pinned full-suite command. "
                    "If delivery truly requires the prohibited operation, report "
                    "a specific blocker; never broaden permissions yourself."
                    if __import__("os").environ.get("HERMES_CONTROLLER_DENIAL_MESSAGES") == "1"
                    and approval_callback is not None else
''' + OLD + '''                )
'''


def adapt(source):
    if source.count(OLD) != 1 or NEW in source:
        raise ValueError('pinned denial message changed')
    return source.replace(OLD, NEW)


if __name__ == '__main__':
    path = Path('/opt/hermes/tools/approval.py')
    path.write_text(adapt(path.read_text()))
