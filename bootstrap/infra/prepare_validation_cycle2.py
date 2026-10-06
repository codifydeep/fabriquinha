"""Preserve baseline and queue exact-contract validation cards, while paused."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess
import yaml

ROOT=Path('/opt/data')
CONTROL=ROOT/'governance/rehearsal'
BOARD=ROOT/'kanban/boards/rehearsal-20260912'
PROFILES=('produto','designer','cto','techlead','backend_data','frontend','mobile','devops','quality_security')
CLI='/opt/hermes/.venv/bin/hermes'

def cli(*args):
    return subprocess.check_output([CLI,'kanban','--board',BOARD.name,*args],text=True)

def main():
    os.umask(0o077)
    db=sqlite3.connect(BOARD/'kanban.db')
    db.row_factory=sqlite3.Row
    if db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone():
        raise ValueError('running card: cannot prepare maintenance cycle')
    for name in PROFILES:
        cfg=yaml.safe_load((ROOT/'profiles'/name/'config.yaml').read_text())
        if cfg['model']!={'default':'qwen3.5:9b','provider':'ollama-local'}:
            raise ValueError('model drift '+name)
    baseline=CONTROL/'baselines'
    baseline.mkdir(exist_ok=True)
    target=baseline/'cycle-1.json'
    if not target.exists():
        document={table:[dict(r) for r in db.execute('SELECT * FROM '+table)]
            for table in ['tasks','task_runs','task_events','task_comments']}
        document.update(original_workspaces_removed=True,original_artifacts_not_recovered=True)
        transcripts=[]
        for run in document['task_runs']:
            metadata=json.loads(run['metadata'] or '{}')
            sid=metadata.get('worker_session_id')
            if not sid: continue
            path=ROOT/'profiles'/run['profile']/'state.db'
            with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as session:
                session.row_factory=sqlite3.Row
                info=session.execute('SELECT id,model,tool_call_count,input_tokens,output_tokens FROM sessions WHERE id=?',(sid,)).fetchone()
                messages=[dict(r) for r in session.execute('SELECT id,role,content,tool_calls,tool_name,timestamp FROM messages WHERE session_id=? ORDER BY id',(sid,))]
                transcripts.append(dict(profile=run['profile'],session=dict(info) if info else {},messages=messages))
            session.close()
        document['transcripts']=transcripts
        target.write_text(json.dumps(document,ensure_ascii=False,indent=2))
    db.close()
    journal=CONTROL/'cycle-2-cards.json'
    if journal.exists():
        print(journal.read_text()); return
    regression=CONTROL/'fixture/test_score.py'
    sha=hashlib.sha256(regression.read_bytes()).hexdigest()
    shape='{"task":"SEU_CARD","stage":"scratch-validation","deployment_performed":false,"regression_sha256":"'+sha+'","tests_run":NUMERO_REAL,"red_failures":FALHAS_REAIS}'
    tdd=json.loads(cli('create','ENSAIO-C2 — TDD com evidências e relatório verificáveis',
        '--initial-status','blocked','--assignee','backend_data','--workspace','scratch',
        '--max-runtime','15m','--max-retries','2','--idempotency-key','rehearsal-c2-tdd','--json',
        '--body',f'''Somente scratch. Copie {CONTROL}/fixture/score.py e test_score.py para seu scratch.
Preserve test_score.py byte a byte, SHA256 {sha}.
winner(a,b): A se a>=12; senão B se b>=12; senão None.
TDD: primeiro escreva test_new_score.py com 5 testes novos (A vence, B vence, ninguém vence,
ambos>=12 dá A, A exatamente12/B11 dá A). Execute a suíte completa e observe falhas reais.
python3 -m unittest discover -v > red.log 2>&1
Só então implemente score.py; rode a MESMA suíte > green.log 2>&1.
Leia os logs. Nunca invente quantidade: conte o número em Ran N tests.
Salve validation-result.json com o formato {shape}. Não houve deploy nem há homologação do CEO.
Comente comandos/resultados. Solicite kanban_request_review com reviewer="techlead" (nome do perfil,
não username Telegram). Corrija erros de ferramenta sem repetir argumentos iguais.
REVISOR: rode testes, confira logs e JSON; divergência => request_changes ao backend_data.
Não corrija artefatos do autor. Se tudo correto, kanban_complete.
Se comando for negado, não encapsule em script para contornar; registre bloqueio e causa.
Use sha256sum test_score.py para hash, sem python -c. Não criar cards, editar infra ou produto.'''))
    qa=json.loads(cli('create','ENSAIO-C2 — QA da exata entrega e retenção',
        '--initial-status','blocked','--parent',tdd['id'],'--assignee','quality_security','--workspace','scratch',
        '--max-runtime','15m','--max-retries','2','--idempotency-key','rehearsal-c2-qa','--json',
        '--body',f'''Após pai {tdd['id']} done, use kanban_show para obter workspace_path.
Copie sem modificar score.py,test_score.py,test_new_score.py,red.log,green.log do pai para seu scratch.
Execute python3 -m unittest discover -v > qa.log 2>&1. Não reescreva testes nem logs do pai.
Confira sha256sum test_score.py == {sha}. Leia red.log,green.log,qa.log.
Salve validation-result.json: {shape}; use SEU id no campo task e os números reais dos logs.
Não alegar pós-deploy, release homologada ou necessidade de aprovação técnica pelo CEO.
Comente resultados; solicite revisão nativa a reviewer="techlead". Revisão independente deve
pedir mudanças se faltar evidência, e só concluir se dados/artefatos concordarem.
Não usar python -c ou contornar negações. Não modificar pai, infra ou produto.'''))
    contracts=json.loads((BOARD/'validation-contracts.json').read_text()) if (BOARD/'validation-contracts.json').exists() else {}
    for task,owner in [(tdd,'backend_data'),(qa,'quality_security')]:
        contracts[task['id']]=dict(regression_sha256=sha,minimum_tests=6,implementer=owner,cycle=2)
    contracts[qa['id']]['parent']=tdd['id']
    (BOARD/'validation-contracts.json').write_text(json.dumps(contracts,indent=2))
    journal.write_text(json.dumps(dict(tdd=tdd['id'],qa=qa['id']),indent=2))
    statepath=CONTROL/'execution.json'
    state=json.loads(statepath.read_text()); state['phase']='ENSAIO_2_EVIDENCIAS'
    statepath.write_text(json.dumps(state,indent=2))
    for name in PROFILES:
        soul=ROOT/'profiles'/name/'SOUL.md'
        text=soul.read_text()
        marker='# Regras de validação — ciclo 2\n'
        if marker not in text:
            soul.write_text(marker+'''Números de testes devem vir da saída real, não de estimativas.
Este ensaio não faz deploy. Não inventar pós-deploy ou homologação pelo CEO.
Revisor não corrige o artefato do autor: usa request_changes.
reviewer é nome de perfil (techlead), nunca username Telegram.
Não contornar comandos negados com scripts. Hash: usar sha256sum.
\n'''+text)
    uid=pwd.getpwnam('hermes').pw_uid
    for file in [target,journal,statepath,BOARD/'validation-contracts.json']:
        os.chown(file,uid,uid)
    os.chown(baseline,uid,uid)
    cli('unblock',tdd['id']); cli('unblock',qa['id'])
    print(journal.read_text())

if __name__=='__main__': main()
