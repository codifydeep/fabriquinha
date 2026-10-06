"""Expose a completed native review as an explicitly historical dashboard board."""
import json,os,sqlite3,shutil
from pathlib import Path

source=Path('/review-source/board/kanban.db')
target=Path('/opt/data/kanban/boards/pr21-review-history')
target.mkdir(exist_ok=False)
with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src:
    assert src.execute('SELECT status FROM tasks WHERE id=?',('t_6716d63e',)).fetchone()==('done',)
    assert not src.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    with sqlite3.connect(target/'kanban.db') as dst:
        src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
(target/'READ_ONLY').write_text('Historical snapshot; not a live board; never dispatch.\n')
(target/'HISTORICAL_MIRROR').write_text('PR21 review completed; original /review/board.\n')
(target/'board.json').write_text(json.dumps(dict(slug='pr21-review-history',name='PR21 — Revisão concluída (histórico)',
    description='Cópia histórica somente leitura do ensaio isolado. Não é sincronização ao vivo nem homologação.',archived=False)))
for path in [target,*target.iterdir()]:os.chown(path,10000,10000)
print('Historical board created: pr21-review-history; card t_6716d63e remains done.')
