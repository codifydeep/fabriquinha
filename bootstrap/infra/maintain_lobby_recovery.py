"""Scoped operator maintenance; snapshot before native Kanban classification."""
import json,sqlite3,shutil,time
from pathlib import Path
from hermes_cli import kanban_db as kb

def main():
    root=Path('/control');board=Path('/board');native=kb.connect(board/'kanban.db')
    if native.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone():raise RuntimeError('active worker; maintenance refused')
    (board/'MAINTENANCE').write_text('Recovery v2 upgrade; preserve all evidence.\n')
    dest=root/'backups'/('recovery-v2-'+str(int(time.time())));dest.mkdir(parents=True)
    for folder,label in ((root,'control'),(board,'board')):
        out=dest/label;out.mkdir()
        for source in folder.glob('*.db'):
            a=sqlite3.connect(source);b=sqlite3.connect(out/source.name);a.backup(b)
            if b.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('backup integrity failed')
            a.close();b.close()
        for source in folder.glob('*.json'):shutil.copyfile(source,out/source.name)
    for name in ('team-packets','pr-packets'):
        if (root/name).exists():shutil.copytree(root/name,dest/name)
    cfg=json.loads((root/'config.json').read_text());changed=[]
    for tid,title,status in native.execute("SELECT id,title,status FROM tasks WHERE status='blocked'").fetchall():
        if tid not in cfg['cards'] and (title.startswith('TDD-') or title.startswith('RELEASE-')):
            reason='WAITING_DEPENDENCY: planned backlog; no worker failure. Tech Lead owns prerequisite/capability activation. Full release remains incomplete.'
            if not kb.schedule_task(native,tid,reason=reason):raise RuntimeError('classification failed '+tid)
            kb.add_comment(native,tid,'techlead',reason);changed.append(tid)
    # Diagnostic cards have no dependents/workspace. Archive only after explicit checks.
    for tid,label in (('t_0992aa33','RESOLVED_HISTORY: PR23 integrated at 89d0ae0ec1adb51a0aab11cb1ff47974d3d1c24c; preserve original failed run.'),('t_9187c9a8','SUPERSEDED_DIAGNOSIS: recovery-v2 will diagnose the same open PR24. Not resolved or delivered.'),('t_e70a7fb9','SUPERSEDED_DIAGNOSIS: preserve failed constrained-tool diagnosis; PR24 remains open.')):
        task=kb.get_task(native,tid)
        if not task or task.status=='archived':continue
        if task.status!='blocked' or task.workspace_path or task.worker_pid:raise RuntimeError('unsafe history archive '+tid)
        # Keep native rows and all transcripts; never mark the incident delivered.
        tables={r[0] for r in native.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in tables:
            if 'depend' not in table:continue
            cols=[r[1] for r in native.execute('PRAGMA table_info('+table+')')]
            for col in cols:
                if col.endswith('_id') and native.execute('SELECT 1 FROM '+table+' WHERE '+col+'=?',(tid,)).fetchone():raise RuntimeError('diagnostic has graph links '+tid)
        kb.add_comment(native,tid,'techlead',label)
        if not kb.archive_task(native,tid):raise RuntimeError('archive failed '+tid)
    print(json.dumps(dict(backup=str(dest),waiting_dependencies=changed,maintenance=True)))
if __name__=='__main__':main()
