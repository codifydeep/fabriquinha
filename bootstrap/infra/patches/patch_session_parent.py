from pathlib import Path

TARGET = Path('/opt/hermes/gateway/session.py')
ANCHOR = '        _db.append_message(\n            session_id=session_id,\n'
BLOCK = '''        from session_parent_guard import ensure_session_parent
        ensure_session_parent(self, session_id, _db)
'''


def apply(source):
    if BLOCK in source:
        return source
    if source.count(ANCHOR) != 1:
        raise ValueError('unknown transcript append entry; refusing patch')
    return source.replace(ANCHOR, BLOCK + ANCHOR)


if __name__ == '__main__':
    TARGET.write_text(apply(TARGET.read_text()))
