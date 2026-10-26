# Status do projeto — 26 de outubro de 2026

**Homologação assistida concluída; autonomia ponta a ponta ainda não qualificada.**
O caminho atual usa Hermes + Kanban nativos e operações determinísticas. Multica
e Temporal não participam dessa execução. O legado permanece preservado.

## Evidência mais recente

O [PR 58](https://github.com/codifydeep/descartavel2/pull/58) chegou a `HOMOLOGADA`
no commit `122176a2e424ca6306b2aea41fa091287f98fd9e`. Foram comprovados os oito
testes, controles negativos, revisão independente, CI local no SHA do PR e no
commit integrado, implantação, rollback/restauração e QA AC1/AC2. Saúde e
identidade HTTP foram conferidas novamente; a main do produto ficou inalterada.
O mesmo bundle imutável foi referenciado até a aceitação final.

A equipe recuperou autonomamente um handoff incompleto do frontend. A integração
exigiu reparo externo de uma regressão da CI; portanto, **não conta como S4 sem
intervenção**. As provas, diagnósticos e contadores anteriores foram preservados.
O [PR 57](https://github.com/codifydeep/descartavel2/pull/57) já havia demonstrado a
correção restrita de expectativa QA. O [ADR 0004](ADR-0004-SCOPED-REPAIR.md)
continua delimitando essa autoridade; adições normais não usam essa exceção.

## P2 — Validação e custos

O [ADR 0005](ADR-0005-VALIDATION-AND-ACCOUNTING.md) está implementado e qualificado:

- Instalações novas capturam os scripts de validação num bundle imutável. Jobs,
  grafo da release, aceitação e atividades de modelo referenciam esse pin.
- O relay preserva custo, cache e raciocínio informados pelo provedor. O SDK
  atribui consumo à atividade por recibo local; nenhum prompt é analisado para
  essa finalidade. Dados ausentes continuam desconhecidos.
- `runtime costs` lê o relatório autenticado sem inferência, alteração de
  política, reset do contador ou remoção de pausa.
- 306 testes do núcleo passaram. A prova física executou treze jobs
  Docker/Chromium; o checkout foi alterado durante a fixture e os validadores
  fixados continuaram sendo usados. Todos esses jobs foram aposentados.
- Nove atividades SDK/11 respostas HTTP locais validaram atribuição, custos
  sintéticos, autenticação e preservação de pausa financeira. Zero chamadas
  pagas nessas provas; decisões programadas não qualificam autonomia.

O novo S4 submeteu o mesmo brief autorizado, obteve revisão do plano, Red/freeze,
Green, controles e revisão da entrega. O frontend encerrou uma atividade sem
handoff; Lead executou SPIKE e o controlador retomou a fase, que depois recebeu
aprovação independente. Essa recuperação ocorreu sem intervenção externa.

O PR 58 foi inicialmente bloqueado na integração: a CI confundiu adição de testes com alteração de testes preexistentes.
Lead/CTO mantiveram o impedimento, sem aprovação fictícia. **Esse ensaio não
qualifica S4 autônomo**, pois exigiu reparo externo do controlador. Após a correção,
a integração foi retomada de forma assistida e homologada; o diagnóstico CTO e
os contadores foram preservados.

A regressão foi reproduzida por teste antes da correção. A condição agora exige
a exceção de revisão somente quando um teste antigo muda ou desaparece. Adições
normais continuam passando pela revisão/freeze e pela suíte completa. As provas
recusam adicionar um teste junto com alteração, remoção ou substituição de um
antigo. A fixture executa agora a entrada real da CI com Git local nos dois
caminhos: funcionalidade nova e correção QA revisada. Passou em treze jobs
Docker/Chromium, sem modelo ou GitHub, retirando todos os jobs ao final.

O contador real mais recente é **6.780/7.000**, com 220 chamadas restantes;
modelo Claude Haiku, saída máxima 16.384 tokens e nenhum fallback. O ciclo novo
usou 57 chamadas e registrou US$ 0,147579 em custos retornados pelo provedor.
56 chamadas têm vínculo de atividade resolvido; uma permanece sem atribuição,
com custo incluído no total e sem inferência por horário ou prosa.
Esse valor não estima custos históricos ausentes nem substitui fatura. O relay
está parado e não há workers, claims, sandboxes pendentes ou efeitos incertos.
A retomada não acrescentou chamadas ao modelo. O ciclo concluído está em
manutenção; sua homologação permanece disponível. Antes do próximo ciclo limpo,
rever a formatação de comentários técnicos: URLs de PR em prosa administrativa
podem acionar o guard nativo `active_pr`. Referências de recibos preservam a
evidência sem duplicar dados ou desabilitar esse guard.

## Evolução comprovada e próximas fronteiras

| Marco | O que passou | O que falta |
|---|---|---|
| S0/S1 | Referência e integração Hermes/Kanban; upstream sem patches | Não constitui entrega de produto |
| S2/S3 | TDD, revisão, operações e recuperação delimitada em provas isoladas | Julgamento real completo continua separado das fixtures |
| P1/P3 | Recuperação assistida até homologação pelo PR 57 | Não qualifica autonomia |
| P2 | Bundle fixado até homologação; custos reais observados | Uma chamada sem vínculo explícito de atividade |
| P4/S4 | Recuperação automática e homologação assistida do PR 58 | Brief aprovado → homologação sem intervenção técnica externa |
| P5/S5 | Mecanismos parciais | Segunda versão, regressão, memória entre perfis e recuperação real |
| P6/S6 | Preparação parcial | Instalação reproduzível em outro repo e corte do legado |
| P7/S7 | Não iniciado | Retomar Truco após qualificação |

Não há promessa de recuperação universal ou ausência universal de starvation.
Um bloqueio preservado com responsável é preferível a sucesso fictício; ele
continua sendo uma pendência de entrega. A outbox foi qualificada localmente,
mas não há transporte Telegram real configurado nesta instalação.

O [roadmap](ROADMAP.md) rege a sequência. As revisões de
[24/10](SIMPLIFICATION-REVIEW-2026-10-24.md),
[25/10](EXECUTION-REVIEW-2026-10-25.md) e
[26/10](EXECUTION-REVIEW-2026-10-26.md) preservam a análise e os contratos.
Versões anteriores deste status continuam no Git; não são ordens para reativar
ensaios históricos nem evidências de qualificações ainda pendentes.
