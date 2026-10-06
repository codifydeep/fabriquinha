"""Render the reviewed source templates onto the dedicated baseline branch.

No credential files, old plans, sessions or backups are copied into Git.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import yaml
from install_company_contract import MISSIONS

ROOT = Path('/Users/weber/Documents/projetos_pessoais_desenv/hermes/truco-online')
SOURCE = Path(__file__).resolve().parent


def main():
    branch = subprocess.check_output(['git','-C',str(ROOT),'branch','--show-current'],text=True).strip()
    if branch != 'codex/restart-baseline-20260911':
        raise ValueError('baseline branch required')
    execution = json.loads(Path('/opt/data/governance/execution.json').read_text())
    if execution.get('product_dispatch_enabled'):
        raise ValueError('product must remain fenced')
    rendered = []
    def write(relative, text):
        target = ROOT / relative
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(text)
        if target.suffix == '.sh':
            target.chmod(0o755)
        rendered.append(str(relative))
    for path in (SOURCE / 'restart-base').rglob('*'):
        if path.is_file():
            write(path.relative_to(SOURCE / 'restart-base'),path.read_text())
    contract = (SOURCE / 'company-contract.md').read_text()
    write('AGENTS.md',contract)
    write('docs/governance/company-contract.md',contract)
    write('.hermes/skills/company-delivery-contract/SKILL.md',
          '---\nname: company-delivery-contract\ndescription: Contrato canônico de execução da equipe Hermes.\n---\n\n' + contract)
    for profile,mission in MISSIONS.items():
        write(f'.hermes/team/profiles/{profile}/SOUL.md',f'# Perfil {profile}\n\n{mission}\n\n' + contract)
        path = ROOT / '.hermes/team/configs' / (profile + '.yaml')
        config = yaml.safe_load(path.read_text())
        config['model'] = {'default':'qwen3.5:9b','provider':'ollama-local'}
        config.setdefault('kanban',{}).update(dispatch_in_gateway=False,auto_decompose=False,
            review_dispatch=True,max_in_progress=2,max_in_progress_per_profile=1,failure_limit=2)
        write(path.relative_to(ROOT),yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
    for name in ('review-matrix.md','tdd-policy.md','docker-resource-naming.md'):
        source = SOURCE / 'governance' / name
        if source.exists():
            write('docs/governance/' + name,source.read_text())
    write('scripts/ci/run-project-checks.sh',(SOURCE/'run-project-checks.sh').read_text())
    write('scripts/ci/check-docker-naming.sh',(SOURCE/'check-docker-naming.sh').read_text())
    ignore = ROOT / '.gitignore'
    text = ignore.read_text()
    for pattern in ('.worktrees/','backups/','.rehearsal/','*.bundle'):
        if pattern not in text.splitlines():
            text += '\n' + pattern + '\n'
    write('.gitignore',text)
    hashes = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(rendered)}
    write('.hermes/team/generated-manifest.json',json.dumps({'source':'company-contract.md and reviewed restart templates','files':hashes},indent=2) + '\n')
    print(json.dumps({'rendered':len(rendered),'branch':branch}))


if __name__ == '__main__':
    main()
