# Documentação da Fabriquinha

Referência: **27 de outubro de 2026**. Plataforma experimental; S4 técnico
qualificado, autonomia geral e distribuição ainda não concluídas. Documentos públicos descrevem contratos,
arquitetura, resultados agregados e limites. Instalações, transcrições, bancos,
snapshots e recibos operacionais completos permanecem privados.

## Ordem de leitura

1. [Status atual](STATUS.md): o que foi comprovado e o que falta.
2. [Revisão da execução de 26/10](EXECUTION-REVIEW-2026-10-26.md): evolução,
   divergência de QA, simplificação do retrabalho e custos; refinamentos aceitos
   posteriormente no [ADR 0004](ADR-0004-SCOPED-REPAIR.md).
3. [Validação fixada e custos](ADR-0005-VALIDATION-AND-ACCOUNTING.md): bundle
   imutável, atribuição por atividade e tratamento de custos desconhecidos.
4. [Roadmap vigente](ROADMAP.md): próxima sequência e critérios de saída.
5. [Plano aprovado de 24/10](SIMPLIFICATION-REVIEW-2026-10-24.md) e
   [ADR 0001](ADR-0001-HERMES-FIRST.md): estratégia Hermes + Kanban.
6. [Arquitetura](ARCHITECTURE.md) e [instalação/limites](SETUP.md):
   distinguir caminho novo e referência histórica.

O [README principal](../README.md) apresenta os diagramas atuais. O aceite
posterior do [ADR 0003](ADR-0003-BEHAVIOR-CONTROL-TARGETS.md) autorizou o F1;
as correções offline não autorizam consumo adicional nem homologam o S4.

## Provas delimitadas do caminho Hermes

| Documento | O que qualifica |
|---|---|
| [S1](HERMES-S1-QUALIFICATION.md) | Kanban/dispatcher nativos e fronteira Docker |
| [S2](HERMES-S2-QUALIFICATION.md) | Mecanismos Red, freeze, Green e controles |
| [S3](HERMES-S3-QUALIFICATION.md) | Cadeia determinística de integração, deploy e QA |
| [S4](HERMES-S4-QUALIFICATION.md) | Primeira entrega técnica por agentes reais, sem intervenção externa, com limites explícitos |
| [Contratos S5](S5-CONTRACT-QUALIFICATION.md) | Regressão existente com CI restrita e projeção histórica de decisões |
| [Entrega S5](HERMES-S5-QUALIFICATION.md) | Segunda homologação com memória e recuperação reais; sete intervenções preservadas |
| [S6](S6-PORTABILITY-PLAN.md) | Export e operação pausada em clone/board novos; instalação completa e entrega portátil pendentes |
| [Agentes](HERMES-AGENT-QUALIFICATION.md) | SDK, ferramentas e sessões |
| [Runtime](HERMES-RUNTIME-QUALIFICATION.md) | Serviço, reinício e worker órfão |
| [Recuperação](HERMES-RECOVERY-QUALIFICATION.md) | Diagnóstico Lead/CTO em cenários delimitados |
| [Notificações](HERMES-NOTIFICATIONS-QUALIFICATION.md) | Outbox, falha de conexão e ACK |
| [Integração](HERMES-INTEGRATION-QUALIFICATION.md) | Esperas, publicação e implantação conectadas |
| [Operações](HERMES-OPERATIONS-QUALIFICATION.md) | Admissão, pausa e retomada |
| [Intake](HERMES-INTAKE-QUALIFICATION.md) | Brief, perguntas, aprovação e plano |
| [Provedor](HERMES-PROVIDER-QUALIFICATION.md) | Relay e espera sem perder orçamento funcional |
| [TDD de navegador](BROWSER-TDD-QUALIFICATION.md) | Chromium real em Red/Green e isolamento |

Resultados determinísticos não são julgamento autônomo de modelo. Um turno
concluído não aprova sua entrega; uma entrega aprovada não homologa a release.
Somente a cadeia completa com evidências permite `HOMOLOGADA`.

## Referências históricas

[VALIDATION](VALIDATION.md), [QA-PROTOCOL-RECOVERY](QA-PROTOCOL-RECOVERY.md) e
[PATCH-RECEIPTS](PATCH-RECEIPTS.md) preservam contratos e qualificações de outras
etapas. Verificar a arquitetura e data de cada seção antes de usar procedimentos.

As versões extensas anteriores de README, STATUS e ROADMAP permanecem no Git.
Não são próximas tarefas do caminho Hermes nem instruções para reativar o legado.
