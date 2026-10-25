# Status do projeto — 25 de outubro de 2026

**Caminho atual:** Hermes + Kanban nativos e executor determinístico. Multica e
Temporal não participam do caminho novo; a instalação legada permanece pausada.

**R1/F1 e R2 limitado qualificados offline; nova tentativa S4 real iniciada.**
O proprietário aprovou o refinamento F1, implementado e validado com
Chromium/Docker. As provas R1/R2 usaram zero chamadas pagas. O novo S4 usa
Claude Haiku sob cota específica autorizada, com relay isolado e perfis limpos.
As tentativas anteriores permanecem pausadas e preservadas.

A [revisão da execução](EXECUTION-REVIEW-2026-10-25.md) é a referência atual para
achados e próximos passos. O [plano de 24/10](SIMPLIFICATION-REVIEW-2026-10-24.md)
continua sendo a estratégia aprovada. O [ADR 0003](ADR-0003-BEHAVIOR-CONTROL-TARGETS.md)
registra o aceite e os limites do contrato F1; recibos antigos permanecem históricos.

## Evolução comprovada

| Etapa | Evidência | Pendência |
|---|---|---|
| S0/S1 | Referência e integração Hermes/Kanban qualificados, upstream sem patches | Não constitui entrega de produto |
| S2 | Contrato 2 deriva alvos do Red e riscos independentes; prova Chromium preserva teste auxiliar | Julgamento semântico real e entrega S4 ainda necessários |
| S3 | Cadeia revalidada no contrato 2: dois incrementos, 11 atividades SDK, 17 respostas locais, Git/deploy/QA/rollback | PR e integração de feature por agentes reais; GitHub/CI ainda simulados nesta prova |
| S4 | Nova fronteira sob contrato 2; perfis limpos, CI local do SHA inicial verde e brief idêntico com aprovação condicional reaplicada | Planejamento, Red/revisão/freeze, Green/controles, PR/CI, integração, deploy e QA desta tentativa |
| S5 | Mecanismos parciais | Segunda versão, regressão, memória entre perfis e recuperação |
| S6 | Preparação parcial | Instalação limpa em outro repo e troca do caminho ativo |
| S7 | Não iniciado | Retomada do Truco após qualificação |

Na tentativa real anterior, QA recebeu mudanças, corrigiu e obteve aprovação
independente dos testes. A pausa humana interrompeu a implementação de forma
controlada. **Essa pausa não é uma falha do ensaio.** A alteração do contrato
exigiu nova fronteira; suas provas não foram importadas para a nova tentativa.
Até agora, nenhuma release S4 foi homologada autonomamente.

As cinco fronteiras identificadas pela auditoria não eram cinco execuções
completas: quatro não qualificaram entrega e a última ficou incompleta e pausada.
A nova fronteira posterior a R2 está em execução. A aprovação de brief reutilizado comprova continuidade do
aceite, não uma nova descoberta autônoma de produto.

## Impedimentos encontrados na revisão

1. **Qualidade — corrigida em fonte:** o contrato 2 exige os alvos derivados do
   Red e riscos adicionais justificados pelo revisor. O teste auxiliar continua
   na suíte completa. Recibos históricos não são convertidos; o S4 antigo não
   pode ser retomado como se tivesse produzido provas desse contrato.
2. **Recuperação — R2 qualificado offline:** planejamento e integração agora
   despacham diagnóstico técnico com snapshot, experimento e orientação completos.
   A revisão retoma na mesma fase. A triagem nativa despacha o CTO, mas permanece
   bloqueada quando não há operação segura; o contador nativo não é zerado.
   Isso não equivale a recuperação universal nem a julgamento do modelo real.
3. **Autoridade:** falta caminho versionado para corrigir contrato de testes
   após freeze, sem alteração da entrega antiga e sem intervenção do operador.
4. **Contexto — parcial:** achados completos e proposta anterior do plano agora
   chegam ao novo worker, qualificados em nove atividades SDK/11 respostas locais.
   Memória arquitetural entre versões permanece em S5.
5. **Distribuição:** imagens locais históricas e preparação parcialmente manual
   impedem declarar o kit reproduzível por terceiros.

A outbox está implementada, mas o transporte real não está configurado na
instalação auditada. Notificações em fila não comprovam visibilidade no Telegram.

O núcleo auditado em `98e09069` tinha 19 módulos funcionais mais `__init__`,
5.060 linhas e 233 testes verdes, sem cobrir a contradição. Os testes novos
exercitam alvos, risco adicional, imutabilidade, skip, inventário e legado.
Os **258 testes do núcleo passaram**. Provas locais não equivalem a autonomia,
SLA ou portabilidade.

A revalidação integrada inicialmente encontrou esgotamento dos pools de rede
Docker. A falha foi preservada. Dois relays de ensaios antigos e suas redes
vazias foram retirados com propriedade/leases conferidos e logs arquivados;
volumes e instalação S4 atual foram preservados. A prova seguinte passou em
grupo isolado e retirou automaticamente seu deploy e redes ao terminar.

R2 percorreu dois incrementos dependentes com 15 atividades SDK e 24 respostas
locais: recuperou revisão do plano e falha de integração por Lead → CTO,
concluiu deploy/QA/rollback e retirou os recursos da prova. Outra prova manteve
uma triagem sob responsabilidade do CTO após reinício, recusando retomada
indevida e sem novas chamadas. Ambas usaram zero chamadas pagas; GitHub/CI
foram simulados. Uma tentativa anterior falhou por orientação de DevOps vazando
para a fase QA; foi preservada e o isolamento de fases foi corrigido antes da
prova aprovada. Veja [recuperação](HERMES-RECOVERY-QUALIFICATION.md).

## Próxima sequência

O [roadmap vigente](ROADMAP.md) detalha R0–R5:

- F1 aprovado, corrigido e revalidado fisicamente e na cadeia integrada offline.
- R2 limitado qualificado; nova tentativa S4 sob o contrato 2 em execução.
- Executar uma tentativa S4 completa, com a equipe conduzindo os handoffs.
- Provar S5 e S6 antes de liberar S7.

Não reiniciar diretamente o ensaio com aprovações do contrato antigo. Não iniciar outra
migração, trocar o modelo ou ampliar consumo por conta desta análise.

## Como interpretar progresso

Os percentuais antigos eram estimativas subjetivas de outra arquitetura e foram
retirados deste status. Permanecem no histórico Git; não são uma série comparável
nem sinal de regressão medida. A avaliação passa a distinguir marcos comprovados,
tentativas assistidas, pausas e requisitos ainda sem evidência.

O único sucesso terminal continua sendo `HOMOLOGADA`, com brief coberto,
revisão, PR/CI, commit/imagem implantados, QA, rollback e URL verificáveis.
