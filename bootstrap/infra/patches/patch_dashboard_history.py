from pathlib import Path
path=Path('/opt/hermes/plugins/kanban/dashboard/plugin_api.py')
text=path.read_text()
if 'def _historical_guard' not in text:
    anchor='router = APIRouter()'
    assert text.count(anchor)==1
    replacement='''from fastapi import Depends, Request

def _historical_guard(request: Request):
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    targets = [request.query_params.get('board'), *request.path_params.values(), kanban_db.get_current_board()]
    for slug in targets:
        if slug == 'pr21-review-history':
            raise HTTPException(status_code=403, detail='Historical board is read-only')

router = APIRouter(dependencies=[Depends(_historical_guard)])'''
    text=text.replace(anchor,replacement)
    anchor='    try:\n        kanban_db.init_db(board=board)'
    assert text.count(anchor)==1
    replacement='''    path = kanban_db.kanban_db_path(board=board)
    if (path.parent / 'HISTORICAL_MIRROR').is_file():
        import sqlite3
        conn = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        return conn
    try:
        kanban_db.init_db(board=board)'''
    text=text.replace(anchor,replacement)
    assert text.count('conn = kanban_db.connect(board=slug)')==1
    text=text.replace('conn = kanban_db.connect(board=slug)','conn = _conn(board=slug)')
    backup=path.with_suffix('.py.before-history')
    if not backup.exists():backup.write_text(path.read_text())
    path.write_text(text)
text=path.read_text()
anchor="    if (path.parent / 'HISTORICAL_MIRROR').is_file():"
replacement="""    import os
    allowed = os.environ.get('HERMES_ALLOWED_KANBAN_BOARD')
    if (path.parent / 'HISTORICAL_MIRROR').is_file() or (allowed and path.parent.name != allowed):"""
if anchor in text:
    assert text.count(anchor)==1
    text=text.replace(anchor,replacement)
    path.write_text(text)
compile(path.read_text(),str(path),'exec')
print('Dashboard historical-board read path installed; syntax valid.')
