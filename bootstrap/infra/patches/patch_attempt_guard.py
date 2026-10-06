from pathlib import Path
TARGET = Path('/opt/hermes/hermes_cli/kanban_db.py')
ANCHOR = '    _assert_not_delegated_child_mutation()\n    if getattr(conn, "in_transaction", False):'
BLOCK = '    _assert_not_delegated_child_mutation()\n    from attempt_guard import validate_mutation\n    validate_mutation(conn)\n    if getattr(conn, "in_transaction", False):'


def apply(source):
    if BLOCK in source:
        return source
    if source.count(ANCHOR) != 1:
        raise ValueError('unknown native transaction entry; refusing patch')
    return source.replace(ANCHOR,BLOCK)


if __name__ == '__main__':
    TARGET.write_text(apply(TARGET.read_text()))
