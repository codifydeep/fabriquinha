# ADR 0003 — Controles negativos dos comportamentos demonstrados

Data: 25/10/2026. Estado: **aprovado pelo proprietário**, resposta explícita
“Aprovar o refinamento F1”. Origem: [auditoria da execução](EXECUTION-REVIEW-2026-10-25.md).

## Problema

Exigir que todo método de teste novo falhe por mutação do aplicativo cria uma
contradição quando há testes auxiliares que só verificam metadados imutáveis.
Esses testes continuam protegidos e executados; seus resultados não dependem
do comportamento que uma mutação do produto remove.

## Decisão

O contrato de controles do caminho novo passa à versão **2**:

1. O controlador deriva os alvos obrigatórios das falhas reais de assertion do
   Red validado. Os alvos não são escolhidos pelo implementador.
2. O revisor independente verifica cobertura do aceite, relevância do Red e
   testes que passam. Pode exigir controles adicionais por `control_risks`,
   associando caso existente da suíte e justificativa concreta.
3. O freeze registra `control_contract=2` e `control_cases`. Todo alvo derivado
   do Red permanece obrigatório; alvos adicionais precisam do parecer exato.
4. Green, controles e revisão executam a suíte completa congelada. Um teste
   auxiliar fora dos alvos continua obrigatório, protegido e descoberto.
5. Cada alvo exigido precisa ser derrubado por mutação legítima do produto,
   por assertion. Skip, erro, inventário parcial, mutação sem efeito e alteração
   de testes/configuração não produzem evidência válida.
6. Red inadequado, teste vacuamente verde ou risco sem cobertura exige mudanças
   na revisão. A classificação semântica não é demonstrada por um parser ou
   pela quantidade de casos.

`control_risks` pertence apenas à aprovação dos testes. Não permite remover
alvos automáticos, alterar artefatos, importar recibos ou mudar o gate na revisão
da implementação. Casos duplicados, desconhecidos ou sem justificativa são
recusados. Os dados permanecem em recibos existentes, sem novo serviço.

## Compatibilidade e autoridade

Recibos antigos permanecem históricos. O caminho atual recusa Red/freeze de
outra versão; não acrescenta campos a evidências antigas. Nova configuração ou
revisão do contrato exige nova fronteira de ensaio e evidências próprias.

O freeze é conferido contra o job Red e o parecer exatos. A publicação valida
esse contrato antes de qualquer efeito Git/GitHub. Aprovação de produto,
exceção de infraestrutura e conclusão de card não dispensam esses requisitos.

A tentativa real anterior permanece preservada e operacionalmente pausada.
Esta decisão não a converte em homologada e não autoriza aumento de quota.

## Qualificação

Testes do núcleo cobrem caso auxiliar preservado, risco adicional obrigatório,
alvo adulterado, controle sem efeito, seleção parcial, skip, teste modificado e
recibo histórico. A prova de [TDD no navegador](BROWSER-TDD-QUALIFICATION.md)
percorreu Red, freeze, Green e controle com Chromium/Docker reais, mantendo o
caso auxiliar verde e na suíte completa.

A cadeia integrada foi revalidada com dois incrementos dependentes, 11 atividades
SDK e 17 respostas HTTP locais, Git/build/deploy/QA/rollback reais. O deploy e
as duas redes dessa prova foram retirados após arquivar as evidências. GitHub/CI
e decisões dos agentes foram simulados; não houve chamadas pagas.

Essas provas usam decisões programadas. Não demonstram julgamento de um modelo
nem substituem S4 com PR, CI e homologação reais.
