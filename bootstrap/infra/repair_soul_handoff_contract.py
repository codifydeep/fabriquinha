#!/usr/bin/env python3
"""Install idempotent worktree and handoff safety rules in team SOULs."""

from pathlib import Path


ROOT = Path("/opt/data/profiles")
PROFILES = (
    "produto", "designer", "cto", "techlead", "backend_data", "frontend",
    "mobile", "devops", "quality_security",
)
START = "<!-- truco-runtime-handoff-v2:start -->"
END = "<!-- truco-runtime-handoff-v2:end -->"
COMMON = f"""

{START}
# Isolamento e handoffs — contrato de runtime v2

- Em worker Kanban, antes de editar ou executar Git, confirme que `pwd` é exatamente o `workspace_path` do card e que a branch corresponde ao card. Se não corresponder, bloqueie com evidência.
- Nunca edite o checkout raiz nem leia, copie, resete ou reutilize outro `.worktrees/<id>`. Dependências válidas chegam somente por `origin/release/vX.Y` depois de revisão e integração.
- Não passe `workspace_path` ao criar um handoff. O Hermes deve criar um worktree novo identificado pelo ID do filho.
- Todo card criado por um worker inclui obrigatoriamente o card corrente como pai; dependências adicionais podem ser incluídas. Assim o filho não inicia antes da revisão do pai.
- Somente workers `GRAPH-*` e `RECOVERY-*` criam filhos. `PLAN-*`, governança e implementações produzem seu próprio artefato/revisão e não fazem fan-out.
- Workers nunca criam cards `RELEASE-*`. Existe um único controlador sentinela por versão, administrado pelo orquestrador e nunca despachado como execução.
- Depois de `gave_up`, não reative nem clone o card por conta própria. O watchdog cria um `RECOVERY-<id>` idempotente para diagnóstico do Tech Lead e revisão do CTO.
- Um plano é produzido e revisado antes de o grafo ser materializado. O grafo também é revisado antes que seus filhos sejam liberados.
{END}
"""


def main() -> None:
    for profile in PROFILES:
        path = ROOT / profile / "SOUL.md"
        text = path.read_text(encoding="utf-8")
        if START in text:
            before, rest = text.split(START, 1)
            _, after = rest.split(END, 1)
            text = before.rstrip() + COMMON + after
        else:
            text = text.rstrip() + COMMON
        temp = path.with_suffix(".md.new")
        temp.write_text(text.rstrip() + "\n", encoding="utf-8")
        temp.chmod(path.stat().st_mode & 0o777)
        temp.replace(path)
        print(f"{profile}: updated")


if __name__ == "__main__":
    main()
