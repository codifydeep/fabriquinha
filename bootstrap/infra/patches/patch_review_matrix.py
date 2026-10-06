from pathlib import Path

TARGET = Path('/opt/hermes/hermes_cli/kanban_db.py')
ANCHOR = '        assignee_sql = ", assignee = ?"\n'
BLOCK = '''        # Enforce the company matrix across CLI, dashboard and tools.
        from review_policy import validate_review
        matrix_error = validate_review(canonical_implementer, reviewer)
        if matrix_error:
            return _ret(False, matrix_error)
'''

def apply(source):
    if BLOCK in source:
        return source
    if source.count(ANCHOR) != 1:
        raise ValueError('unknown reviewer gate; refusing patch')
    return source.replace(ANCHOR, BLOCK + ANCHOR)

if __name__ == '__main__':
    TARGET.write_text(apply(TARGET.read_text()))
