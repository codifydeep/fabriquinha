"""Operator: queue a fresh experiment, retaining cycle-2 evidence unchanged."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sqlite3

control=Path('/opt/data/governance/rehearsal')
board=Path('/opt/data/kanban/boards/rehearsal-20260912')
def cli(*args):
    return subprocess.check_output(['/opt/hermes/.venv/bin/hermes','kanban','--board',board.name,*args],text=True)

def main():
    os.umask(0o077)
    journal=control/'cycle-3-cards.json'
    if journal.exists():
        print(journal.read_text()); return
    with sqlite3.connect(board/'kanban.db') as db:
        assert not db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(),'pause workers first'
    regression=hashlib.sha256((control/'fixture/test_score.py').read_bytes()).hexdigest()
    fixture=hashlib.sha256((control/'fixture/score.py').read_bytes()).hexdigest()
    command='python3 /opt/hermes/validation_runner.py'
    tdd=json.loads(cli('create','ENSAIO-C3 — TDD com executor padronizado','--initial-status','blocked',
        '--assignee','backend_data','--workspace','scratch','--max-runtime','15m','--max-retries','2',
        '--idempotency-key','rehearsal-c3-tdd','--json','--body',f'''Experimento isolado; não retome arquivos do ciclo 2.
1. Copie score.py e test_score.py de {control}/fixture para seu scratch.
2. Crie somente test_new_score.py usando import unittest e from score import winner.
Escreva cinco testes: A vence (13,0), B vence (0,13), ninguém (0,0), ambos (12,12) dá A, (12,11) dá A.
Não defina winner dentro dos testes. Não crie runners alternativos.
3. Execute {command} red. Ele deve aceitar 6 testes, 4 assertion failures e nenhuma exception de import/stub.
Se rejeitar, leia o erro e corrija os TESTES antes de implementar. Duas falhas idênticas exigem diagnóstico.
4. Só após Red aceito, implemente score.py: A se a>=12, senão B se b>=12, senão None.
5. Execute {command} green. O executor salva logs, hashes e validation-result.json automaticamente.
Não edite logs, recibos ou relatório. Não altere testes entre Red e Green.
6. Solicite revisão com reviewer="techlead". Revisor verifica artefatos, executa suíte completa e pede mudanças ao autor se necessário.
Se qualquer ferramenta negar uma ação, registre o bloqueio; não contorne. Não há deploy nem aprovação técnica do CEO.'''))
    qa=json.loads(cli('create','ENSAIO-C3 — QA da entrega exata','--initial-status','blocked','--parent',tdd['id'],
        '--assignee','quality_security','--workspace','scratch','--max-runtime','15m','--max-retries','2',
        '--idempotency-key','rehearsal-c3-qa','--json','--body',f'''Leia workspace_path do pai {tdd['id']} quando done.
Copie exatamente score.py,test_score.py,test_new_score.py,red.log,green.log,runner-red.json,runner-green.json.
Não reescreva testes nem evidências do pai. No seu scratch execute {command} qa.
O executor grava qa.log e validation-result.json para seu card. Solicite revisão reviewer="techlead".
Não declarar deploy ou homologação. Falha repetida: diagnóstico técnico, não nova implementação.'''))
    path=board/'validation-contracts.json'
    contracts=json.loads(path.read_text())
    for task,owner in [(tdd,'backend_data'),(qa,'quality_security')]:
        contracts[task['id']]=dict(regression_sha256=regression,fixture_sha256=fixture,minimum_tests=6,
            implementer=owner,runner_required=True,cycle=3)
    contracts[qa['id']]['parent']=tdd['id']
    path.write_text(json.dumps(contracts,indent=2))
    journal.write_text(json.dumps(dict(tdd=tdd['id'],qa=qa['id']),indent=2))
    statepath=control/'execution.json'
    state=json.loads(statepath.read_text()); state['phase']='ENSAIO_3_EXECUTOR_TDD'
    statepath.write_text(json.dumps(state,indent=2))
    for file in [path,journal,statepath]: os.chown(file,10000,10000)
    cli('unblock',tdd['id']); cli('unblock',qa['id'])
    print(journal.read_text())

if __name__=='__main__': main()
