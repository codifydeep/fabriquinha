# Roadmap vigente — 25 de outubro de 2026

Referências: [plano aprovado](SIMPLIFICATION-REVIEW-2026-10-24.md),
[revisão da execução](EXECUTION-REVIEW-2026-10-25.md) e [status](STATUS.md).

Este documento substitui a lista antiga de próximos passos da ponte Multica/ACP.
A estratégia é Hermes + Kanban e uma camada pequena de entrega. Não iniciar outro
orquestrador, novo banco de memória ou migração de modelo nesta fase.

O proprietário aprovou F1, registrado no [ADR 0003](ADR-0003-BEHAVIOR-CONTROL-TARGETS.md).
O contrato 2 e o feedback do plano estão implementados e passaram em provas
offline delimitadas. A tentativa S4 real mais recente chegou ao Green e terminou
em triagem nos controles. Foi preservada; feedback e exploração foram corrigidos
e qualificados offline para outra fronteira. Este roadmap não amplia a cota.

## Antes do próximo ensaio pago

### R0 — Fixar contrato e referência

Aceite de F1 registrado; referência anterior preservada. A retomada do ensaio
real exige nova fronteira, sem importar aprovações do contrato antigo.

Preservar os recibos, testes e fronteiras atuais. Registrar o aceite do refinamento
de controles derivados do Red e riscos revisados, distinguindo testes auxiliares. A pausa
humana não desqualifica sozinha a tentativa. Uma mudança de runtime ou gate
exige outra fronteira e novas evidências, sem aprovação retroativa.

**Saída:** política inequívoca, referência recuperável e escopo de correção limitado.

### R1 — Eliminar a contradição do gate de controles

Concluído no escopo offline: quatro jobs Docker/Chromium passaram com teste
auxiliar imutável na suíte completa e alvo comportamental derivado do Red.
A cadeia integrada passou com dois incrementos, regressão, 11 atividades SDK,
17 respostas locais, Git/deploy/QA/rollback e retirada dos recursos da prova.
Decisões programadas e GitHub/CI simulados não substituem S4 real.

Derivar os alvos obrigatórios das falhas reais do Red e congelar os adicionais
justificados pelo revisor. Revisão independente deve confirmar a cobertura dos
comportamentos de aceite e riscos. Reutilizar os IDs e recibos existentes.
Testes auxiliares continuam na suíte completa, mas não precisam falhar por
mutação do aplicativo quando não dependem dele.

**Saída:** caso comportamento + teste auxiliar aceito sob o contrato novo;
remoção unilateral de alvo, critério sem cobertura, skip, teste alterado, descoberta
reduzida e mutante sem efeito rejeitados. Sem seleção parcial de suíte ou
dispensa de revisão independente.

### R2 — Completar feedback e destinos de impedimentos conhecidos

Concluído no escopo delimitado offline. A cadeia com dois incrementos recuperou
revisão do plano e integração Lead → CTO, preservou fase e orientação completa,
e concluiu deploy/QA/rollback: 15 atividades SDK, 24 respostas locais, zero
chamadas pagas. GitHub/CI e decisões foram programados. A prova separada de
triagem recusou retomada indevida e preservou o bloqueio com responsável CTO
após reinício, sem novas chamadas. Não há reset do breaker nem reparação
universal; retrabalho versionado de testes continua em S5.

Transmitir achados completos de revisão do plano, tratar bloqueios de
planejamento/integração e `triage`, preservar a fase e impedir repetição idêntica
sem diagnóstico. Cada impedimento deve ter responsável e próxima operação
possível. Conferir schema/handler/prompt/configuração preparados.

**Saída:** testes determinísticos de devolução de plano, falha de integração,
segundo bloqueio, reinício e espera humana correta. Não precisa completar toda
S5; uma reparação sem operação segura deve ser declarada como limite visível.

## Provas de autonomia e reutilização

### R3 / S4 — Uma entrega completa pequena

Mesmo brief aprovado, stack qualificada e modelo. Preparação e orçamento
verificados antes de liberar; o operador observa, a equipe executa os handoffs.

A recuperação real pelo Lead levou o QA até o freeze independente e a
implementação até Green. Os controles ainda não foram aceitos; a triagem manteve
responsável CTO, sem encerrar a release. A correção posterior informa casos
cobertos/ausentes e impede lotes exploratórios acima de 120 segundos no schema
e handler. Passou offline sem dispensar controles ou alterar testes congelados.
Repetir em fronteira limpa com essas pré-condições, mantendo o modelo e o teto
de saída e sem importar provas técnicas anteriores.

A nova fronteira foi iniciada após CI inicial verde e igualdade canônica do
brief. O CTO aprovou seu plano e o QA está produzindo Red. A tentativa anterior
em triagem permanece preservada; não conta como release entregue.

**Saída:** Green → controles → revisão → PR/CI → integração → Docker → QA/rollback
→ `HOMOLOGADA`, com URL e evidências, sem intervenção técnica externa depois do
aceite. Reparos externos tornam a tentativa assistida. Não substituir essa prova
por outro ensaio genérico de pré-Red.

### R4 / S5 — Segunda versão, memória e recuperação

Dois incrementos dependentes, regressão preservada e outro perfil com sessão
nova usando decisões/interfaces versionadas em Git. Qualificar substituição de
ADR e pelo menos uma recuperação real conduzida por Lead/CTO.

Implementar a operação limitada de retrabalho de testes congelados: nova autoria,
revisão e freeze, preservando a versão antiga e invalidando provas dependentes.
Não usar edição direta de cards/arquivos para contornar o contrato.

**Saída:** segunda release funcional, memória útil entre perfis e recuperação
com evidência nova. Infraestrutura repetitiva pode usar falhas determinísticas.

### R5 / S6 — Instalação por terceiros e caminho único

Imagem reconstruível sem base local histórica; configuração única; preparação e
operação documentadas; segundo repo por configuração, sem alteração de código
específico. Provar restauração e rollback. Retirar o caminho antigo só depois.

**Saída:** reprodução a partir de um clone e inputs privados do novo operador,
sem copiar bancos, conversas, snapshots ou credenciais da instalação de referência.

### S7 — Retomar Truco

Avançar por fatias reais, ampliando a stack somente conforme demanda e qualificação.
A primeira fatia não encerra toda a versão de produto. Não declarar suporte
universal a stacks a partir da demonstração Python/HTTP.

## Regras de foco

- Preservar TDD, revisão independente, proteção da baseline, PR e CI no SHA exato.
- Zero novo serviço ou framework para corrigir uma lacuna de contrato.
- Duas tentativas da mesma classe sem evidência nova: rever o mecanismo antes
  de gastar mais; não aumentar limites automaticamente.
- Medir entregas e intervenções, não quantidade de módulos ou testes do kit.
- Atualizar este roadmap quando uma etapa mudar; manter diários privados e
  histórico no Git, sem acrescentar cada incidente ao README.
