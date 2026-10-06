"""Read-only installed skill/role drift check. No model requests."""
import hashlib,json,sys
from pathlib import Path
import yaml
root=Path('/opt/data');version='truco-company-skills-20260918.1'
installed=root/'skills/company'/version
receipt=json.loads((root/'governance'/('installed-'+version+'.json')).read_text())
matrix=json.loads((installed/'manifest.json').read_text())['profiles'];errors=[]
for name,expected in receipt['skills'].items():
    if hashlib.sha256((installed/name/'SKILL.md').read_bytes()).hexdigest()!=expected:errors.append('skill:'+name)
for profile,names in matrix.items():
    cfg=yaml.safe_load((root/'profiles'/profile/'config.yaml').read_text())
    for name in names:
        if str(installed/name) not in cfg.get('skills',{}).get('external_dirs',[]):errors.append(profile+':'+name)
    if cfg.get('model')!={'default':'deepseek/deepseek-v4-flash-0731','provider':'openrouter'}:errors.append(profile+':model')
lock=json.loads((installed/'sources.lock.json').read_text())
for name,source in lock.items():
    for path,expected in source['files'].items():
        if hashlib.sha256((installed/'vendor'/name/path).read_bytes()).hexdigest()!=expected:errors.append('upstream:'+name+':'+path)
print(json.dumps(dict(passed=not errors,profiles=len(matrix),skills=len(receipt['skills']),drift=errors)))
sys.exit(bool(errors))
