# Status do projeto — 25 de outubro de 2026

**Caminho atual:** Hermes + Kanban nativos e executor determinístico. Multica e
Temporal não participam do caminho novo; a instalação legada permanece pausada.

**Desenvolvimento pausado por solicitação do proprietário.** Esta atualização
decorre de uma auditoria de código e evidências. Não iniciou agentes, chamadas
ao modelo, integração de produto ou implantação.

A [revisão da execução](EXECUTION-REVIEW-2026-10-25.md) é a referência atual para
achados e próximos passos. O [plano de 24/10](SIMPLIFICATION-REVIEW-2026-10-24.md)
continua sendo a estratégia aprovada; refinamentos novos não foram instalados.

## Evolução comprovada

| Etapa | Evidência | Pendência |
|---|---|---|
| S0/S1 | Referência e integração Hermes/Kanban qualificados, upstream sem patches | Não constitui entrega de produto |
| S2 | Red, freeze, isolamento, SDK/sessão, pausa e recibos exercitados | Corrigir incompatibilidade semântica do gate de controles |
| S3 | Cadeia determinística de Git/deploy/QA/rollback; CI local com status real da base | Completar PR e integração de feature por agentes reais |
| S4 | Brief aprovado, plano revisado e testes de navegador corrigidos/congelados; implementação iniciada | Green, controles, revisão, PR, integração, deploy e QA finais |
| S5 | Mecanismos parciais | Segunda versão, regressão, memória entre perfis e recuperação |
| S6 | Preparação parcial | Instalação limpa em outro repo e troca do caminho ativo |
| S7 | Não iniciado | Retomada do Truco após qualificação |

Na tentativa real mais recente, QA recebeu mudanças, corrigiu e obteve aprovação
independente dos testes. A pausa humana interrompeu a implementação de forma
controlada. **Essa pausa não é uma falha do ensaio.** Até agora, nenhuma release
S4 foi homologada autonomamente.

As cinco fronteiras de tentativa identificadas não devem ser somadas como cinco
execuções completas: quatro anteriores não qualificaram entrega; a atual está
incompleta e pausada. A aprovação de brief reutilizado comprova continuidade do
aceite, não uma nova descoberta autônoma de produto.

## Impedimentos encontrados na revisão

1. **Qualidade:** o gate exige mutação que derrube todos os testes novos,
   inclusive um teste que lê apenas um JSON de QA protegido e não depende do
   produto. É um bloqueio futuro demonstrado na lógica do gate, não a causa da
   pausa atual.
2. **Recuperação:** `tests` e `implementation` têm diagnóstico executável;
   planejamento, integração e `triage` não têm cobertura equivalente. Alertar
   um CTO não significa despachar uma intervenção para ele.
3. **Autoridade:** falta caminho versionado para corrigir contrato de testes
   após freeze, sem alteração da entrega antiga e sem intervenção do operador.
4. **Contexto:** achados completos do plano e memória arquitetural entre versões
   precisam de tratamento explícito.
5. **Distribuição:** imagens locais históricas e preparação parcialmente manual
   impedem declarar o kit reproduzível por terceiros.

A outbox está implementada, mas o transporte real não está configurado na
instalação auditada. Notificações em fila não comprovam visibilidade no Telegram.

O núcleo auditado em `98e09069` tem 19 módulos funcionais mais `__init__`,
5.060 linhas. Os **233 testes passaram novamente**; não cobriam a contradição
identificada. Provas locais não equivalem a autonomia, SLA ou portabilidade.

## Próxima sequência

O [roadmap vigente](ROADMAP.md) detalha R0–R5:

- Concordar com o refinamento do contrato de controles e preservar a referência.
- Corrigir a contradição e os caminhos conhecidos de feedback/impedimento offline.
- Executar uma tentativa S4 completa, com a equipe conduzindo os handoffs.
- Provar S5 e S6 antes de liberar S7.

Não reiniciar diretamente o ensaio sob o gate contraditório. Não iniciar outra
migração, trocar o modelo ou ampliar consumo por conta desta análise.

## Como interpretar progresso

Os percentuais antigos eram estimativas subjetivas de outra arquitetura e foram
retirados deste status. Permanecem no histórico Git; não são uma série comparável
nem sinal de regressão medida. A avaliação passa a distinguir marcos comprovados,
tentativas assistidas, pausas e requisitos ainda sem evidência.

O único sucesso terminal continua sendo `HOMOLOGADA`, com brief coberto,
revisão, PR/CI, commit/imagem implantados, QA, rollback e URL verificáveis.
