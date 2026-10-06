"""Remove only checkpointed retired worktrees/branches, with compare checks."""
import argparse
import json
from pathlib import Path
import subprocess
import tarfile
import time

REPO = Path('/Users/weber/Documents/projetos_pessoais_desenv/hermes/truco-online')


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def git(*args):
    return run('git', '-C', str(REPO), *args)


def main(checkpoint):
    journal = json.loads((checkpoint / 'restart-journal.json').read_text())
    if journal.get('phase') != 'ARCHIVED_AND_FENCED':
        raise ValueError('archive not complete')
    if not Path('/opt/data/kanban/boards/truco-online/READ_ONLY').exists():
        raise ValueError('retired board not fenced')
    if any('hermes_cli.kanban_worker' in line for line in run('ps','-eo','args').splitlines()):
        raise ValueError('worker still alive')
    if json.loads(run('gh','pr','list','--repo','codifydeep/truco-online','--state','open','--limit','1000','--json','number')):
        raise ValueError('open PRs require reassessment before cleanup')
    inventory = json.loads((checkpoint / 'inventory.json').read_text())
    archived_refs = dict((line.split()[1],line.split()[0]) for line in inventory['refs'].splitlines())
    report = {'removed_worktrees':[], 'removed_branches':[], 'remote_branches':[], 'deferred':[], 'at':int(time.time())}
    audit = checkpoint / 'cleanup-journal.json'
    if audit.exists():
        report = json.loads(audit.read_text())
    def save():
        audit.write_text(json.dumps(report,indent=2))
    # Compare every saved regular file before permitting --force on dirty work.
    with tarfile.open(checkpoint / 'repository-worktrees.tgz','r:gz') as archive:
        members = archive.getmembers()
        current = git('worktree','list','--porcelain').split('\n\n')
        for entry in current:
            fields = dict(line.split(' ',1) for line in entry.splitlines() if ' ' in line)
            if 'worktree' not in fields:
                continue
            path = Path(fields['worktree'])
            if path == REPO:
                continue
            if not path.is_relative_to(REPO / '.worktrees') or path.parent != REPO / '.worktrees':
                report['deferred'].append({'path':str(path),'reason':'outside exact retired worktree root'})
                continue
            ref = fields.get('branch')
            if archived_refs.get(ref) != fields.get('HEAD'):
                raise ValueError('worktree HEAD changed since checkpoint: ' + str(path))
            expected = inventory['status'].get(str(path))
            actual = run('git','-C',str(path),'status','--porcelain=v1','--untracked-files=all')
            if expected is None or expected != actual:
                raise ValueError('worktree status changed since checkpoint: ' + str(path))
            prefix = 'repository/' + str(path.relative_to(REPO)) + '/'
            saved = {m.name[len(prefix):]:m for m in members if m.name.startswith(prefix) and (m.isfile() or m.issym() or m.islnk())}
            present = {str(p.relative_to(path)) for p in path.rglob('*') if p.is_file() or p.is_symlink()}
            if set(saved) != present:
                raise ValueError('worktree file set changed since checkpoint: ' + str(path))
            for name, member in saved.items():
                file = path / name
                if member.issym():
                    if not file.is_symlink() or str(file.readlink()) != member.linkname:
                        raise ValueError('worktree symlink changed: ' + str(file))
                else:
                    with archive.extractfile(member) as old, file.open('rb') as live:
                        while True:
                            chunk = old.read(1024*1024)
                            if chunk != live.read(len(chunk) or 1):
                                raise ValueError('worktree file changed: ' + str(file))
                            if not chunk:
                                break
            report['pending_removal'] = {'path':str(path),'sha':fields['HEAD'],'backup':str(checkpoint)}
            save()
            git('worktree','remove','--force',str(path))
            report['removed_worktrees'].append(str(path))
            report.pop('pending_removal',None)
            save()
    checked_out = {line[7:] for line in git('worktree','list','--porcelain').splitlines() if line.startswith('branch ')}
    remote = {line.split()[1]:line.split()[0] for line in git('ls-remote','--heads','origin').splitlines()}
    for ref, sha in archived_refs.items():
        if not ref.startswith('refs/heads/') or ref in checked_out:
            continue
        branch = ref[len('refs/heads/'):]
        if not branch.startswith(('truco-online/','wt/','feat/','codex/governance-maintenance-')):
            continue
        exists = subprocess.run(['git','-C',str(REPO),'rev-parse','--verify',ref],capture_output=True,text=True)
        if exists.returncode:
            continue
        if exists.stdout.strip() != sha:
            report['deferred'].append({'branch':branch,'reason':'local SHA changed'})
            continue
        if ref in remote:
            if remote[ref] != sha:
                report['deferred'].append({'branch':branch,'reason':'remote SHA differs from checkpoint'})
                continue
            git('push',f'--force-with-lease={ref}:{sha}','origin',':' + ref)
            report['remote_branches'].append(branch)
            save()
        git('branch','-D',branch)
        report['removed_branches'].append({'branch':branch,'sha':sha})
        save()
    save()
    print(json.dumps(report),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--checkpoint',type=Path,required=True)
    main(parser.parse_args().checkpoint)
