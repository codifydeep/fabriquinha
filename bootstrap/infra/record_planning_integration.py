"""Record verified publication CI without authorizing review, merge or coding."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from coordination_store import CoordinationStore


def gh(*args):
    return json.loads(subprocess.check_output(['gh', *args], text=True))


def main():
    path = Path('/opt/data/governance/execution.json')
    raw = path.read_bytes()
    state = json.loads(raw)
    assert state['attempt'] == 'truco-restart-20260911'
    assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
    assert state['planning_status']['approved'] == state['planning_status']['total'] == 4
    pr = gh('pr', 'view', '19', '--repo', 'codifydeep/truco-online', '--json',
            'headRefOid,baseRefName,state,isDraft,url,files')
    run = gh('run', 'view', '35125317346', '--repo', 'codifydeep/truco-online', '--json',
             'headSha,status,conclusion,event,url')
    assert pr['state'] == 'OPEN' and pr['isDraft']
    assert pr['baseRefName'] == 'codex/restart-baseline-20260911'
    assert pr['headRefOid'] == run['headSha'] == 'b0215f8b6a0c184c98819d82721faa2da603ddad'
    assert run['status'] == 'completed' and run['conclusion'] == 'success'
    assert run['event'] == 'workflow_dispatch'
    assert '.github/workflows/quality-gates.yml' not in {f['path'] for f in pr['files']}
    evidence = dict(pr=pr['url'], sha=pr['headRefOid'], ci=run['url'],
                    ci_event=run['event'], status='CI_PASSED_REVIEW_ADAPTER_PENDING',
                    independent_pr_review=False, agent_trial_started=False,
                    note='Manual workflow does not run the pull_request-only trusted base guard. '
                         'Local guard passed separately; not merge authorization.')
    state['publication_validation'] = evidence
    state['next_action'] = ('Preparar e validar operações restritas de revisão de PR pelos agentes; '
                            'PR #19 tem CI manual verde, sem revisão independente ou merge. '
                            'Nenhum novo ensaio de agentes despachado.')
    store = CoordinationStore('/opt/data/governance/coordination.db')
    try:
        with store.transaction(state['attempt']):
            if store.get(state['attempt'], 'publication-validation', pr['headRefOid']) != evidence:
                store._put(state['attempt'], 'publication-validation', pr['headRefOid'], evidence)
        store.enqueue(state['attempt'], 'publication-ci-' + pr['headRefOid'], json.dumps(dict(
            profile='techlead', chat_id=state['telegram_chat_id'], text=
            '🔎 Integração documental: CI manual do PR #19 passou no runner local, SHA b0215f8. '
            'A revisão independente de PR pelos agentes ainda requer operações restritas próprias; '
            'não há novo ensaio de agentes em execução. Próximo passo: preparar e validar esse fluxo. '
            'Sem merge e sem liberação de código do Truco. ' + run['url'])))
    finally:
        store.close()
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as out:
        temporary = Path(out.name)
        json.dump(state, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    try:
        temporary.chmod(path.stat().st_mode & 0o777)
        assert path.read_bytes() == raw, 'execution changed; rerun safely'
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()
