"""Operator-only migration after backup, while the rehearsal is fenced."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from coordination_store import CoordinationStore

BOARD=Path('/opt/data/kanban/boards/rehearsal-20260912')
CONTROL=Path('/opt/data/governance/rehearsal')
OLD=('t_388c8d1b','t_a521af2d','t_fe70f1b8','t_a533ad5e')

def cli(*args):
    return subprocess.check_output(['/opt/hermes/.venv/bin/hermes','kanban','--board',BOARD.name,*args],text=True)

def main(cycle=4,old=OLD):
    os.umask(0o077)
    assert (BOARD/'MAINTENANCE').exists()
    with sqlite3.connect(BOARD/'kanban.db') as db:
        assert not db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone()
    journal=CONTROL/f'cycle-{cycle}-cards.json'
    if journal.exists(): print(journal.read_text()); return
    for task in old:
        cli('comment',task,f'Tentativa anterior preservada e não aprovada. Substituída pelo ciclo {cycle}, sem declarar entrega.')
        cli('archive',task)
    store=CoordinationStore(CONTROL/'coordination.db')
    try:
        rows=store.db.execute("SELECT id,data FROM records WHERE attempt=? AND kind='incident'",(BOARD.name,)).fetchall()
        with store.transaction(BOARD.name):
            for row in rows:
                data=json.loads(row['data'])
                if data['task'] in old:
                    data.update(status='superseded',superseded_by=f'cycle-{cycle}',reason='Tentativa arquivada sem aprovação; não reativar ocorrências antigas')
                    store._put(BOARD.name,'incident',row['id'],data)
    finally: store.close()
    regression=hashlib.sha256((CONTROL/'fixture/test_score.py').read_bytes()).hexdigest()
    fixture=hashlib.sha256((CONTROL/'fixture/score.py').read_bytes()).hexdigest()
    runner='python3 /opt/hermes/validation_runner.py'
    author=json.loads(cli('create',f'ENSAIO-C{cycle} — Entrega imutável e retrabalho pelo autor',
        '--assignee','backend_data','--initial-status','blocked','--workspace','scratch',
        '--max-runtime','15m','--max-retries','2','--idempotency-key',f'rehearsal-c{cycle}-author','--json',
        '--body',f'''Experimento novo, somente scratch, sem deploy.
Na PRIMEIRA execução:
1. Copie score.py e test_score.py de {CONTROL}/fixture para seu scratch.
2. Crie test_new_score.py com import unittest e from score import winner. Não defina winner no teste.
Cinco testes: (13,0)->A; (0,13)->B; (0,0)->None; (12,12)->A; (12,11)->A.
3. Execute {runner} red. Exige 6 testes e 4 falhas de assertion, sem erros de importação.
4. Só após Red aceito implemente score.py: A se a>=12, senão B se b>=12, senão None.
5. Execute {runner} green. Não edite os logs, recibos ou relatório gerados.
6. Solicite kanban_request_review com reviewer="techlead". O controlador congela a entrega.
Quando receber changes_requested, LEIA o feedback. Altere somente o que foi solicitado;
preserve os testes e o Red já aceito, não reinicie o exercício nem restaure a fixture.
Execute Green e solicite nova revisão ao techlead. Não crie runners alternativos.
Este ensaio exige uma rodada de mudança documental pedida pelo revisor. Não antecipe a documentação.
Negações não autorizam contornos. Não alterar infra, outros cards ou solicitar decisão técnica ao CEO.'''))
    qa=json.loads(cli('create',f'ENSAIO-C{cycle} — QA da revisão imutável aprovada',
        '--assignee','quality_security','--initial-status','blocked','--workspace','scratch','--parent',author['id'],
        '--max-runtime','15m','--max-retries','2','--idempotency-key',f'rehearsal-c{cycle}-qa','--json',
        '--body',f'''Depois do pai {author['id']} aprovado, use review_fetch_parent sem argumentos.
Essa ferramenta importa o snapshot exato aprovado para seu scratch. Não copie pastas mutáveis.
Execute {runner} qa. Não modifique testes, implementação, logs ou recibos herdados.
Solicite kanban_request_review com reviewer="techlead". A validação deve referenciar a entrega congelada.
Não houve deploy nem homologação. Não criar cards ou pedir decisão técnica ao CEO.'''))
    contracts=json.loads((BOARD/'validation-contracts.json').read_text())
    for task,owner in [(author,'backend_data'),(qa,'quality_security')]:
        contracts[task['id']]=dict(regression_sha256=regression,fixture_sha256=fixture,minimum_tests=6,
            implementer=owner,runner_required=True,immutable_review=True,cycle=cycle)
    contracts[author['id']]['review_probe']=True
    contracts[qa['id']]['parent']=author['id']
    (BOARD/'validation-contracts.json').write_text(json.dumps(contracts,indent=2))
    journal.write_text(json.dumps(dict(tdd=author['id'],qa=qa['id']),indent=2))
    state_path=CONTROL/'execution.json'; state=json.loads(state_path.read_text())
    state['phase']=f'ENSAIO_{cycle}_REVISAO_IMUTAVEL'; state_path.write_text(json.dumps(state,indent=2))
    for name in ['produto','designer','cto','techlead','backend_data','frontend','mobile','devops','quality_security']:
        soul=Path('/opt/data/profiles')/name/'SOUL.md'; text=soul.read_text()
        marker='# Modos de execução controlados — revisão imutável\n'
        if marker not in text:
            soul.write_text(marker+'''O modo vem da claim do Kanban, nunca da sua interpretação do objetivo original.
Em REVIEW ONLY siga apenas o roteiro de revisão: review_inspect, review_validate e decisão.
Não refaça implementação, testes ou Red. Negações de escrita são proteção esperada.
Em incidente/SPIKE use review_diagnose para obter comparação de hashes e próxima ação.
Não declare bug do controlador sem evidência; não altere permissões nem peça arquitetura ao CEO.
\n'''+text)
    for path in [BOARD/'validation-contracts.json',journal,state_path]: os.chown(path,10000,10000)
    cli('unblock',author['id']); cli('unblock',qa['id'])
    print(journal.read_text())

if __name__=='__main__': main()
