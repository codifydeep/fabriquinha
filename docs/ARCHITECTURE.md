# Arquitetura atual

A fonte de verdade do trabalho é o Kanban do Hermes. A Fabriquinha acrescenta
operações determinísticas para assegurar autoria, revisão independente,
execução de testes e entrega verificável. Não usa Multica ou Temporal.
Os diagramas de componentes e fluxo estão no [README](../README.md).

## Fronteiras do código

- `runtime.py`, `board.py`, `kanban_lane.py`: integração com o dispatcher e o
  estado nativo, autenticação da execução e pausa persistente.
- `hermes.py`, `profile_policy.py`: SDK, sessões, perfis e ferramentas permitidas
  por fase. O modelo segue a política de provedor, sem fallback automático.
- `artifacts.py`, `effects.py`: snapshots/recibos e journal de efeitos externos.
  Um efeito incerto é observado antes de qualquer repetição.
- `quality.py`, `suite.py`, `browser.py`, `executor.py`: evidências de testes,
  controles negativos e validação isolada. Resultado diagnóstico não é aprovação.
- `recovery.py`, `repairs.py`: diagnóstico técnico e reparos delimitados, com
  proveniência e nova revisão. Sem aprovação do próprio trabalho.
- `publication.py`, `deployment.py`: GitHub, CI vinculada ao SHA, Compose, QA e rollback.
- `intake.py`, `releases.py`, `historical.py`: brief, grafo da release e contexto
  durável entre entregas; transcrições não substituem artefatos aprovados.
- `channel.py`, `channel_gateway.py`, `notifications.py`: comandos autorizados
  e outbox. Mensagem isolada não transfere responsabilidade.
- `source.py`, `operations.py`, `provider.py`: export fechado, operação e limites
  de consumo. A instalação executa uma fonte congelada, não o checkout de desenvolvimento.

## Isolamento e autoridade

Workers operam em espaços atribuídos; revisores examinam entregas imutáveis.
Testes usam containers descartáveis com restrições específicas da fase. Somente
operações autorizadas do controlador têm acesso a infraestrutura e publicação.
Os perfis não ganham esse acesso por uma resposta do proprietário no chat.

Homologação exige a cadeia completa de evidências do artefato implantado. CI verde,
worker vivo ou conclusão textual não bastam. Cada revisão deve continuar vinculada
à identidade e revisão exatas. Consulte os ADRs no [índice](README.md).

## Operação e evolução

Nove perfis podem atuar conforme a necessidade; não existe obrigação de nove
handoffs para cada card. A capacidade local é delimitada pela instalação.
Recuperação e autonomia foram demonstradas somente nos cenários documentados.

Instrumentação operacional e análise de produto são preocupações distintas.
Papéis futuros de observabilidade e experimentação poderão orientar métricas e
pesquisas; coleta de dados e testes A/B não são recursos já qualificados.
A avaliação de instrumentação deve constar do planejamento quando aplicável.
