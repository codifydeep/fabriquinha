"""Maintenance-only operator install with backups and real Hermes skill loading."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import time
import yaml

ROOT=Path('/opt/data'); PRIVATE=Path('/deliveries'); INPUT=Path('/input')
BOARD=ROOT/'kanban/boards/truco-online-r2-20260911'
PROFILES=('produto','designer','cto','techlead','backend_data','frontend','mobile','devops','quality_security')
REVIEWERS=('produto','cto','techlead','quality_security')

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def main():
    os.umask(0o077)
    assert (BOARD/'MAINTENANCE').exists()
    with sqlite3.connect(BOARD/'kanban.db') as db:
        assert not db.execute("SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL AND status='running'").fetchone()
    resume=os.environ.get('HERMES_SKILL_INSTALL_BACKUP')
    backup=Path(resume) if resume else ROOT/'governance'/('skills-recovery-backup-'+time.strftime('%Y%m%d-%H%M%S'))
    assert backup.parent==ROOT/'governance' and backup.name.startswith('skills-recovery-backup-')
    if not resume:
        backup.mkdir()
        with tarfile.open(backup/'configuration.tgz','w:gz') as archive:
            for profile in PROFILES:
                for name in ('config.yaml','SOUL.md'):
                    file=ROOT/'profiles'/profile/name; archive.add(file,arcname=str(file.relative_to(ROOT)))
            for file in (BOARD/'planning.json',PRIVATE/'planning-config.json',ROOT/'governance/planning-installed-manifest.json'):
                archive.add(file,arcname='control/'+file.name)
        with sqlite3.connect(BOARD/'kanban.db') as source, sqlite3.connect(backup/'kanban.db') as dest:
            source.backup(dest); assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    with tarfile.open(backup/'configuration.tgz') as archive:
        for entry in archive:
            if entry.isfile(): assert archive.extractfile(entry).read() is not None
    skill=ROOT/'skills/research/grill-me'
    if skill.exists(): assert digest(skill/'SKILL.md')==digest(INPUT/'skills/grill-me/SKILL.md')
    else: shutil.copytree(INPUT/'skills/grill-me',skill)
    previous=ROOT/'profiles/produto/skills/software-development/grill-me'
    if previous.exists():
        assert not previous.is_symlink() and not (backup/'grill-me-before').exists()
        shutil.move(str(previous),str(backup/'grill-me-before'))
    skilltext=(skill/'SKILL.md').read_text()
    for profile in REVIEWERS:
        path=ROOT/'profiles'/profile/'config.yaml'; cfg=yaml.safe_load(path.read_text())
        dirs=cfg.setdefault('skills',{}).setdefault('external_dirs',[])
        if '/opt/data/skills/devops/sdlc-review' not in dirs: dirs.append('/opt/data/skills/devops/sdlc-review')
        if profile=='produto' and str(skill) not in dirs: dirs.append(str(skill))
        path.write_text(yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False))
    soul=ROOT/'profiles/produto/SOUL.md'
    if '<!-- GRILL-ME-HERMES-1 -->' not in soul.read_text():
        soul.write_text(soul.read_text()+'\n\n<!-- GRILL-ME-HERMES-1 -->\n'+skilltext)
    manifest_path=ROOT/'governance/planning-installed-manifest.json'
    manifest=json.loads(manifest_path.read_text()); manifest['produto/SOUL.md']=digest(soul)
    manifest['skills/research/grill-me/SKILL.md']=digest(skill/'SKILL.md')
    save(manifest_path,manifest)
    data=json.loads((PRIVATE/'planning-config.json').read_text())
    data['coordination_db']='/opt/data/governance/coordination.db'
    save(PRIVATE/'planning-config.json',data); save(BOARD/'planning.json',data)
    proof=dict(attempt=data['attempt'],profiles={},grill_me={},upstream_commit='959a8e9f1edc3adbe2f7e3054bb6fbefa6696260',backup=str(backup))
    for profile in REVIEWERS:
        env=dict(os.environ,HERMES_HOME=str(ROOT/'profiles'/profile))
        code='import json; from agent.skill_commands import build_preloaded_skills_prompt; p,l,m=build_preloaded_skills_prompt(["sdlc-review"]); print(json.dumps(dict(loaded=l,missing=m,prompt_bytes=len(p))))'
        result=subprocess.run(['/opt/hermes/.venv/bin/python','-c',code],env=env,capture_output=True,text=True,check=True)
        loaded=json.loads(result.stdout)
        assert loaded['loaded']==['sdlc-review'] and not loaded['missing'], (profile,loaded)
        proof['profiles'][profile]=dict(loaded,config_sha256=digest(ROOT/'profiles'/profile/'config.yaml'))
    code='import json; from agent.skill_commands import build_preloaded_skills_prompt; p,l,m=build_preloaded_skills_prompt(["grill-me"]); print(json.dumps(dict(loaded=l,missing=m,prompt_bytes=len(p))))'
    result=subprocess.run(['/opt/hermes/.venv/bin/python','-c',code],env=dict(os.environ,HERMES_HOME=str(ROOT/'profiles/produto')),capture_output=True,text=True,check=True)
    proof['grill_me']=json.loads(result.stdout)
    assert proof['grill_me']['loaded']==['grill-me'] and not proof['grill_me']['missing']
    save(PRIVATE/'planning-preflight.json',proof)
    save(ROOT/'governance/planning-skills-preflight.json',proof)
    for path in [BOARD/'planning.json',manifest_path,ROOT/'governance/planning-skills-preflight.json',skill,*skill.rglob('*')]:
        os.chown(path,10000,10000)
    print(json.dumps(proof,ensure_ascii=False))

if __name__=='__main__': main()
