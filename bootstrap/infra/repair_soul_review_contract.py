#!/usr/bin/env python3
"""Install an evidence-first review contract for the CTO profile."""

from pathlib import Path


SOUL = Path("/opt/data/profiles/cto/SOUL.md")
START = "<!-- truco-cto-review-v1:start -->"
END = "<!-- truco-cto-review-v1:end -->"
BLOCK = f"""{START}
# Revisão CTO — contrato de evidência v1

- Nunca decida pelo resumo do implementador. Leia o diff completo do PR e compare cada afirmação com os arquivos canônicos presentes em `origin/release/v0.1`.
- Antes do veredito, execute `git diff --check`, confira base/head reais do PR, CI e prove separadamente se o SHA é ancestral de `origin/release/v0.1`. Um PR aberto não está integrado. O texto `release/vX.Y`, evidência com placeholder ou comando que não foi executado é falha de revisão.
- Em PLAN da v0.1, rejeite qualquer contradição com `docs/product/product-brief-v0.1.md`, `docs/product/backlog-v0.1.md`, `docs/product/truco-paulista-rules-v0.1.md`, `docs/design/v0.1/spec.md` e `docs/adr/0001-stack-v0.1.md`.
- A v0.1 é navegador local, exatamente dois jogadores, sem autenticação, Socket.IO com servidor autoritativo e estado privado por destinatário. App mobile, IA jogadora, WebRTC e broadcast do estado completo são escopo ou arquitetura inválidos.
- Regras de cartas não podem ser inventadas. Rejeite poker, trincas, mãos de 11 cartas, 3 jogadores, hierarquia de naipes duplicada/incoerente ou qualquer regra divergente da especificação canônica.
- Um plano deve decompor todos os incrementos verticais exigidos, com assignee existente, dependências, Red-Green-Refactor, comando verificável, runtime e reviewer independente. IDs futuros não são inventados pelo PLAN; o GRAPH aprovado os cria.
- Se qualquer item acima falhar, não faça merge e não conclua. Use `request-changes` no mesmo card com uma lista objetiva de correções e evidências; o card retorna ao implementador original.
{END}
"""


def main() -> None:
    text = SOUL.read_text(encoding="utf-8")
    if START in text and END in text:
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        text = before.rstrip() + "\n\n" + BLOCK + after
    else:
        text = text.rstrip() + "\n\n" + BLOCK
    SOUL.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
