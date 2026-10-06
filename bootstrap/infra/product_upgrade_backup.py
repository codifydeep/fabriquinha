"""Operator-only bounded upgrade backup. No card classification or cleanup."""
import json,shutil,sqlite3,time
from pathlib import Path

def main():
    control=Path('/control');board=Path('/board')
    if not (board/'MAINTENANCE').is_file():raise RuntimeError('maintenance required')
    with sqlite3.connect((board/'kanban.db').as_uri()+'?mode=ro',uri=True) as db:
        if db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone():raise RuntimeError('active execution; backup refused')
    destination=control/'backups'/('process-upgrade-'+str(int(time.time())))
    destination.mkdir(parents=True,exist_ok=False)
    sources=[(control,'control'),(board,'board')]
    profiles=Path('/profiles/profiles')
    if profiles.is_dir():sources.extend((p,'profiles/'+p.name) for p in profiles.iterdir() if p.is_dir())
    databases=0
    for source,label in sources:
        target=destination/label;target.mkdir(parents=True)
        for path in source.glob('*.db'):
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(target/path.name) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('backup integrity failed')
            src.close();dst.close();databases+=1
        names=('config.yaml','SOUL.md') if label.startswith('profiles/') else ('config.json','product-adapter.json')
        for name in names:
            if (source/name).is_file():shutil.copyfile(source/name,target/name)
    for name in ('team-packets','pr-packets'):
        if (control/name).is_dir():shutil.copytree(control/name,destination/name)
    print(json.dumps(dict(backup=str(destination),integrity_checked_databases=databases,credentials_copied=False,cards_changed=False)))

if __name__=='__main__':main()
