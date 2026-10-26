# S5 — Contratos de regressão conhecida e memória

Implementado em 26/10/2026, dentro do refinamento A2 aprovado. O S4 continua
qualificado pela sua revisão original; estes mecanismos não convertem provas
antigas nem qualificam, por si, a continuidade autônoma de uma segunda versão.

## Regressão conhecida

O grafo fornece o SHA de base: seed do repositório ou commit com QA do pacote
anterior. O agente não escolhe um modo nem declara uma exceção. Quando a suíte
completa de base apresenta assertions existentes, a submissão deve ser exatamente
o snapshot original, sem acrescentar ou modificar testes. O controlador executa
novamente Red e exige inventário, casos, posições e detalhes de falha iguais.
Erros de execução, skips e descoberta parcial não qualificam essa evidência.

O recibo `regression_red` identifica os dois jobs e o SHA. O revisor independente
confirma as expectativas e todas as falhas; o freeze preserva os testes completos.
A implementação modifica produto, passa a suíte integral e apresenta controles
negativos para os alvos congelados. Outro revisor valida a entrega imutável.

A CI local tolera uma base vermelha somente quando encontra essa entrega
independentemente aprovada para o snapshot da cabeça, SHA de base, inventário e
falhas exatos. O recibo de CI referencia a revisão que fundamentou a exceção.
Falhas adicionais ou cabeça vermelha nunca produzem status verde. Uma aprovação
dos testes sozinha não autoriza essa CI. O caminho comum continua exigindo base
verde e comportamento novo vermelho; correção restrita de texto QA continua um
terceiro tipo de evidência, com Red histórico explicitamente identificado.

Esta primeira versão do reparo preserva todo o inventário, sem adicionar testes.
Uma lacuna que exija testes novos precisa de trabalho explícito; não duplicar
artificialmente testes existentes para satisfazer o Red comum.

## Memória mínima

Produto, planejador e revisor de plano recebem uma projeção somente leitura da
última release `HOMOLOGADA` do mesmo projeto: commit, referências, resumo de negócio
e decisão técnica com autoria/revisão. A ordem vem dos runs nativos, não do nome
do card. O contexto é limitado a 128 KiB, não inclui conversas ou sessões e não
concede autoridade, aprovação ou ferramentas. O armazenamento continua sendo
Kanban e recibos; não há banco vetorial nem serviço adicional.

Hashes, projeto e origem/revisão são conferidos. Aprovação anterior continua
inválida para novo brief. A projeção também foi lida diretamente dos recibos do
S4 real. Ainda falta provar outro perfil **citando e usando** uma dessas decisões
na segunda versão; disponibilidade no prompt não substitui essa evidência.

## Prova executada e limites

`scripts/qualify_hermes_delivery.py --known-regression` percorreu quatro atividades
SDK nativas e nove respostas locais programadas: Red existente, revisão/freeze,
Green/controle e revisão da entrega. Git e Docker são reais. As entradas reais
de CI de proposta e integração passaram; snapshot sem revisão e base com outro
SHA foram recusados, inclusive quando o conteúdo defeituoso era idêntico.
Os testes permaneceram intactos e os containers descartáveis foram aposentados.

A primeira execução revelou uma lista de tipos desatualizada no sandbox de
revisão. O sandbox passou a consultar a política central de evidências; a segunda
execução qualificou essa correção. A tentativa falha permanece privada e não
foi reclassificada como sucesso.

As decisões programadas não representam julgamento de um modelo. Foram **zero
chamadas pagas** e não houve GitHub, deploy, homologação ou recuperação paga nesse
ensaio. Testes unitários complementares cobrem falha adicional, inventário parcial,
aprovação obsoleta, cabeça vermelha, teste enfraquecido e proveniência de memória.
O [plano S5](S5-CONTINUITY-PLAN.md) mantém a segunda versão e recuperação reais
como fronteiras abertas.
