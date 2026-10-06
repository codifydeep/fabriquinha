"""Operator installation of stage-1 rehearsal. Never enables the product board."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tarfile
import time
import yaml
from coordination_store import CoordinationStore
from install_company_contract import MISSIONS

ROOT=Path('/opt/data')
ATTEMPT='rehearsal-20260912'
CONTROL=ROOT/'governance/rehearsal'
HERMES='/opt/hermes/.venv/bin/hermes'


def cli(*args):
    return subprocess.check_output([HERMES,'kanban',*args],text=True)


def main():
    os.umask(0o077)
    product=json.loads((ROOT/'governance/execution.json').read_text())
    if product.get('product_dispatch_enabled') or product.get('rehearsal_passed'):
        raise ValueError('expected fenced product attempt')
    if not (ROOT/'kanban/boards'/product['board']/'MAINTENANCE').exists():
        raise ValueError('product maintenance fence missing')
    # Read-only product fence must be readable by the supervised hermes user.
    os.chown(ROOT/'governance/execution.json',0,pwd.getpwnam('hermes').pw_gid)
    os.chmod(ROOT/'governance/execution.json',0o640)
    CONTROL.mkdir(parents=True,exist_ok=True)
    backup=CONTROL/'pre-enable-profiles.tgz'
    if not backup.exists():
        with tarfile.open(backup,'w:gz') as out:
            for profile in MISSIONS:
                for name in ['config.yaml','SOUL.md','.env','gateway_state.json']:
                    path=ROOT/'profiles'/profile/name
                    if path.exists(): out.add(path,arcname=str(path.relative_to(ROOT)))
    board=ROOT/'kanban/boards'/ATTEMPT
    if not board.exists():
        cli('boards','create',ATTEMPT,'--name','ENSAIO 1 — Qwen / colaboração',
            '--description','Scratch isolado. Não representa entrega ou homologação do Truco.')
    cli('--board',ATTEMPT,'init')
    store=CoordinationStore(CONTROL/'coordination.db')
    try: store.create_attempt(ATTEMPT,ATTEMPT,'rehearsal-stage-1')
    finally: store.close()
    registry=dict(attempt=ATTEMPT,board=ATTEMPT,phase='ENSAIO_1_COLABORACAO',
        product_dispatch_enabled=False,rehearsal_passed=False,
        ceo_telegram_id=product['ceo_telegram_id'],telegram_chat_id=product['telegram_chat_id'],
        command_bot=product['command_bot'])
    (CONTROL/'execution.json').write_text(json.dumps(registry,indent=2))
    metadata=json.loads((board/'board.json').read_text())
    metadata.update(execution_attempt=ATTEMPT,purpose='isolated-rehearsal-stage-1')
    (board/'board.json').write_text(json.dumps(metadata,indent=2))
    fixture=CONTROL/'fixture'
    fixture.mkdir(exist_ok=True)
    (fixture/'score.py').write_text('def winner(a,b):\n    return None\n')
    regression='import unittest\nfrom score import winner\nclass ExistingRegression(unittest.TestCase):\n    def test_no_winner(self):\n        self.assertIsNone(winner(0,0))\n'
    (fixture/'test_score.py').write_text(regression)
    digest=hashlib.sha256(regression.encode()).hexdigest()
    contract=Path(__file__).with_name('company-contract.md').read_text()
    phase=f'''# Modo ENSAIO_1_COLABORACAO — {ATTEMPT}
O CEO autorizou teste do time com qwen3.5:9b. Não desenvolver Truco agora.
Trabalhe SOMENTE nos cards do board {ATTEMPT} e em seu scratch atribuído.
Não editar repositório do produto, branches, Docker, configurações, perfis ou credenciais.
Não usar modelos externos, downloads ou serviços pagos. Não contornar negações.
Este ensaio inicial usa artefatos scratch e revisão nativa, sem PR artificial.
Omitir PR aqui NÃO é exceção para implementações futuras do produto em worktree.
Backend pede revisão ao techlead; QA também é revisado pelo techlead.
Use request_review/request_changes/complete reais e comentários com caminhos e comandos.
Revisor pode ler e testar o scratch deste card. Não implementar correção: devolva ao autor.
Nunca declarar HOMOLOGADA ou liberar v0.1 com este teste. Se perguntarem, explicar fase.
No Telegram, responder apenas quando mencionado ou em reply; decisões técnicas vão ao CTO.
Para status, informar /kanban@techlead_truco_poc_bot team-status.
'''
    for profile,mission in MISSIONS.items():
        home=ROOT/'profiles'/profile
        config=yaml.safe_load((home/'config.yaml').read_text())
        if config['model']!={'default':'qwen3.5:9b','provider':'ollama-local'}:
            raise ValueError('model drift: '+profile)
        config.setdefault('kanban',{}).update(dispatch_in_gateway=profile=='techlead',
            max_in_progress=2,max_in_progress_per_profile=1,failure_limit=2,
            auto_decompose=False,review_dispatch=True,dispatch_interval_seconds=15)
        config.setdefault('agent',{}).update(max_turns=40)
        (home/'config.yaml').write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
        (home/'SOUL.md').write_text(phase+'\n# Papel\n'+mission+'\n\n'+contract)
        envpath=home/'.env'
        updates={'HERMES_EXECUTION_ATTEMPT':ATTEMPT,'HERMES_KANBAN_BOARD':ATTEMPT,
            'HERMES_TEAM_EXECUTION':str(CONTROL/'execution.json'),
            'HERMES_COORDINATION_DB':str(CONTROL/'coordination.db')}
        lines=[line for line in envpath.read_text().splitlines() if line.split('=',1)[0] not in updates]
        envpath.write_text('\n'.join(lines+[f'{key}={value}' for key,value in updates.items()])+'\n')
        statepath=home/'gateway_state.json'
        state=json.loads(statepath.read_text())
        state.update(desired_state='stopped',gateway_state='stopped',restart_requested=False)
        statepath.write_text(json.dumps(state))
    journal=CONTROL/'cards.json'
    if not journal.exists():
        task=json.loads(cli('--board',ATTEMPT,'create','ENSAIO-1 — TDD de placar e revisão independente',
            '--assignee','backend_data','--workspace','scratch','--max-runtime','12m','--max-retries','2',
            '--idempotency-key',ATTEMPT+':tdd','--json','--body',f'''
Ensaio de colaboração, não produto. No scratch atribuído a este card, copie
{fixture}/score.py e test_score.py. Preserve test_score.py byte a byte (SHA256 {digest}).
Implemente winner(a,b): "A" se a>=12; senão "B" se b>=12; senão None.
Primeiro escreva test_new_score.py para A vence, B vence, ninguém vence e ambos>=12 (A tem prioridade).
Execute python -m unittest discover -v > red.log 2>&1 ANTES de implementar; confirme falhas reais.
Só então implemente e execute suíte completa > green.log 2>&1. Não fabricar logs nem enfraquecer testes.
Registre comandos, exit codes, hash da regressão e caminhos num comentário do card.
Solicite revisão NATIVA ao techlead, não encerre sua própria implementação.
REVISOR: execute suíte, confira casos, logs e hash. Achado => request_changes ao backend_data.
Se correto, conclua via API nativa, com resultado e evidências. Não há PR neste scratch.
Não editar configurações/infra/repo. Não criar outros cards. Não declarar release homologada.'''))
        qa=json.loads(cli('--board',ATTEMPT,'create','ENSAIO-2 — QA da entrega e trilha de handoff',
            '--assignee','quality_security','--parent',task['id'],'--workspace','scratch',
            '--max-runtime','12m','--max-retries','2','--idempotency-key',ATTEMPT+':qa','--json',
            '--body',f'''Após o pai {task['id']} concluído, consulte seus comentários e workspace_path.
Leia os artefatos do pai sem editá-los; rode testes e valide winner(12,12)=="A", winner(0,12)=="B".
Confira hash test_score.py == {digest}, logs Red/Green não vazios e autor/revisor distintos nos eventos.
Salve qa-result.json no SEU scratch com comandos, resultados, evidências e limitações.
Se houver falha, bloqueie este card com diagnóstico específico para Tech Lead; não declare sucesso.
Se correto, peça revisão ao techlead. Revisor valida e conclui. Ensaio 1 não comprova PR/deploy/recovery.
Nunca declarar HOMOLOGADA, modificar produto ou criar release.'''))
        journal.write_text(json.dumps(dict(tdd=task['id'],qa=qa['id']),indent=2))
    user=pwd.getpwnam('hermes')
    for tree in [CONTROL,board]:
        for path in [tree,*tree.rglob('*')]:
            os.chown(path,user.pw_uid,user.pw_gid)
    print(json.dumps(dict(attempt=ATTEMPT,cards=json.loads(journal.read_text()),gateways='still stopped',product='fenced')))


if __name__=='__main__': main()
