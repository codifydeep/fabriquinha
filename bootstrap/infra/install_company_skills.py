"""Idempotent, backed-up Hermes installation; does not enable dispatch."""
import hashlib,json,os,shutil,sqlite3,subprocess,time
from pathlib import Path
import yaml

SOURCE=Path('/input/infra'); DATA=Path('/opt/data')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    os.umask(0o077)
    cfg=json.loads((SOURCE/'skills/manifest.json').read_text())
    version=cfg['version']; destination=DATA/'skills/company'/version
    receipt=DATA/'governance'/('installed-'+version+'.json')
    board=DATA/'kanban/boards/truco-online-r2-20260911/kanban.db'
    with sqlite3.connect(board.as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone():
            raise RuntimeError('Active worker: installation requires idle board')
    backup=DATA/'governance'/('company-skills-backup-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    manifest=DATA/'governance/planning-installed-manifest.json'
    if manifest.exists():shutil.copy2(manifest,backup/manifest.name)
    installed=json.loads(manifest.read_text()) if manifest.exists() else {}
    if not destination.exists():
        destination.mkdir(parents=True)
        for name in sorted({n for v in cfg['profiles'].values() for n in v}):
            shutil.copytree(SOURCE/'skills'/name,destination/name)
        shutil.copytree('/input/vendor/company-skills',destination/'vendor')
        shutil.copy2('/input/vendor/company-skills/sources.lock.json',destination/'sources.lock.json')
        shutil.copy2(SOURCE/'skills/manifest.json',destination/'manifest.json')
    for name in {n for v in cfg['profiles'].values() for n in v}:
        if sha(SOURCE/'skills'/name/'SKILL.md')!=sha(destination/name/'SKILL.md'):
            raise RuntimeError('Installed skill drift: '+name)
    common=(destination/'karpathy-guidelines/SKILL.md').read_text().split('---',2)[2]
    reports={}
    for profile,names in cfg['profiles'].items():
        home=DATA/'profiles'/profile
        (backup/profile).mkdir()
        for file in ('config.yaml','SOUL.md'):shutil.copy2(home/file,backup/profile/file)
        config=yaml.safe_load((home/'config.yaml').read_text())
        dirs=config.setdefault('skills',{}).setdefault('external_dirs',[])
        for name in names:
            path=str(destination/name)
            if path not in dirs:dirs.append(path)
        (home/'config.yaml').write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
        text=(home/'SOUL.md').read_text();marker='<!-- '+version+' -->'
        if marker not in text:
            text+='\n\n'+marker+'\n## Current company skill policy\n'+common+'\n'
            text+='Specialized skill availability: '+', '.join(names)+'. Load only on matching tasks; respect current tool restrictions.\n'
            text+='Current model policy: deepseek/deepseek-v4-flash-0731 via OpenRouter; no fallback. This supersedes historical Qwen-only instructions. Product infrastructure stays local.\n'
            text+='The approved v0.1 brief is not reopened. Generic rehearsals are closed; validate the actual lobby increment. This does not bypass dispatch/review/deploy gates.\n'
            if profile=='quality_security':text+=cfg['qa_3d']+'\n'
            (home/'SOUL.md').write_text(text)
        for file in ('config.yaml','SOUL.md'):
            path=home/file;os.chown(path,10000,10000)
            if profile+'/'+file in installed:installed[profile+'/'+file]=sha(path)
        code='import json;from agent.skill_commands import build_preloaded_skills_prompt;p,l,m=build_preloaded_skills_prompt('+repr(names)+');print(json.dumps(dict(loaded=l,missing=m,bytes=len(p))))'
        out=subprocess.run(['/opt/hermes/.venv/bin/python','-c',code],env=dict(os.environ,HERMES_HOME=str(home)),text=True,capture_output=True,check=True)
        proof=json.loads(out.stdout)
        if set(proof['loaded'])!=set(names) or proof['missing']:raise RuntimeError(profile+': loader failed')
        reports[profile]=proof
    # Readable by the non-root gateways; no credentials are stored here.
    for path in [destination,*destination.rglob('*')]:
        os.chown(path,10000,10000);path.chmod(0o755 if path.is_dir() else 0o644)
    manifest.write_text(json.dumps(installed,indent=2)+'\n');os.chown(manifest,10000,10000)
    result=dict(version=version,backup=str(backup),profiles=reports,
                skills={n:sha(destination/n/'SKILL.md') for n in {n for v in cfg['profiles'].values() for n in v}},
                source_lock_sha256=sha(destination/'sources.lock.json'),dispatch_changed=False)
    receipt.write_text(json.dumps(result,indent=2)+'\n');os.chown(receipt,10000,10000)
    print(json.dumps(result))
if __name__=='__main__':main()
