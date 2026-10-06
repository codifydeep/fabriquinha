#!/usr/bin/env python3
"""Create the reviewed R3 planning chain after quarantining invalid R2 cards."""

import json
import subprocess


HERMES = "/opt/hermes/.venv/bin/hermes"
BASE = [HERMES, "-p", "techlead", "kanban", "--board", "truco-online"]
PROJECT = "p_71f57328"


def run(*args: str) -> str:
    result = subprocess.run([*BASE, *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise SystemExit((result.stderr or result.stdout).strip())
    return result.stdout


def create(title: str, body: str, key: str, parents: tuple[str, ...] = ()) -> str:
    args = [
        "create", title,
        "--body", body,
        "--assignee", "techlead",
        "--workspace", "worktree",
        "--project", PROJECT,
        "--priority", "3000",
        "--max-runtime", "2h",
        "--max-retries", "2",
        "--created-by", "recovery-operator",
        "--idempotency-key", key,
        "--skill", "company-delivery-contract",
        "--skill", "github",
        "--json",
    ]
    for parent in parents:
        args.extend(["--parent", parent])
    return str(json.loads(run(*args))["id"])


def main() -> None:
    plan = create(
        "PLAN-v0.1-R3 — Plano vertical fiel às fontes",
        """Produza somente docs/planning/v0.1-execution-plan-r3.md e abra um PR R3 novo na branch atribuída; não crie cards e não implemente aplicação.

Confirme pwd/branch do card e trabalhe somente no próprio worktree. Baseie cada requisito exclusivamente em docs/product/product-brief-v0.1.md, docs/product/backlog-v0.1.md, docs/product/truco-paulista-rules-v0.1.md, docs/design/v0.1/spec.md e docs/adr/0001-stack-v0.1.md de origin/release/v0.1. O plano R2/commit a070e92 é evidência rejeitada: não copie seu conteúdo.

Invariantes: v0.1 somente navegador responsivo; exatamente 2 jogadores humanos; sem autenticação; Socket.IO e servidor autoritativo; o servidor envia a cada destinatário somente seu estado privado; sem WebRTC, app mobile, AI jogadora, poker, trincas ou mãos inventadas. Copie as regras exatas da especificação, sem reinterpretá-las. Use apenas perfis existentes.

Planeje incrementos pequenos para fundação monorepo; motor puro TDD; lobby/salas; backend autoritativo e contratos; web 2D; cena 3D e privacidade; reconexão; Compose/health/logs/métricas; integração/E2E/regressão/segurança; deploy e validação de homologação. Para cada futuro card: assignee, paths, critérios Red-Green-Refactor, comandos, dependências, max-runtime 2h e reviewer independente. Não invente IDs; GRAPH-R3 os criará.

Antes do commit rode buscas no documento e falhe se encontrar: WebRTC, app mobile, três/3 jogadores, AI jogadora, release/vX.Y, assignee backend ou broadcast de estado completo. Faça commit e push somente da branch atribuída, abra um PR novo com base release/v0.1, confirme CI e use request-review neste card com reviewer cto. Não alegue merge/integração enquanto o PR estiver aberto. Não chame complete.""",
        "r3-plan-v0.1",
    )
    governance = create(
        "GOVERNANCE-v0.1-R3 — Persistir invariantes nos paths canônicos",
        """Depois que PLAN-R3 estiver revisado e integrado, atualize exatamente AGENTS.md e docs/governance/release-lifecycle.md. Não crie outro arquivo substituto e não crie cards. Registre isolamento por worktree; todo filho com pai corrente; somente GRAPH/RECOVERY fazem fan-out; nenhum worker cria RELEASE; revisão independente; links de PR não bloqueiam respawn; reclaim automático após 45 min sem progresso Git; gave_up cria recovery idempotente. Faça commit/push somente da branch atribuída, abra um PR R3 novo contra release/v0.1, confirme diff/CI e solicite review ao cto. Não alegue integração antes do merge e não chame complete.""",
        "r3-governance-v0.1",
        (plan,),
    )
    graph = create(
        "GRAPH-v0.1-R3 — Materializar DAG integrado",
        """Somente após PLAN-R3 e GOVERNANCE-R3 revisados e integrados em origin/release/v0.1, materialize o DAG. Primeiro prove que os dois artefatos canônicos existem na branch remota e que os PRs foram mesclados. Se faltar, bloqueie tecnicamente sem pedir decisão ao CEO. Crie exatamente os cards descritos no plano integrado. Todo filho inclui este GRAPH como pai, usa projeto herdado e worktree novo sem workspace_path explícito, assignee existente, TDD, comandos, max-runtime 2h, duas tentativas e reviewer independente. Cards filhos ficam todo enquanto este GRAPH aguarda revisão. Confira IDs/pais/assignees/skills, registre a tabela e solicite review ao cto. Não crie RELEASE e não implemente código.""",
        "r3-graph-v0.1",
        (plan, governance),
    )
    print(json.dumps({"plan": plan, "governance": governance, "graph": graph}))


if __name__ == "__main__":
    main()
