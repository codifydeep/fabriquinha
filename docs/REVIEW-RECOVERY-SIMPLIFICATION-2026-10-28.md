# Simplificação proposta da recuperação de revisão

Estado: aprovada explicitamente pelo proprietário em 28/10/2026; implementação
instalada em `9096013b`; recuperação real em validação.

Implementação: recibo `review_admission` emitido pelo controlador e revalidado
na leitura; transferência nativa da entrega original; proposta histórica
bloqueada sem aprovação; contexto do diagnóstico entregue ao revisor.
A prova isolada validou recuperação de crash durante aposentadoria da proposta
e transferência, ausência de duplicação, rejeição de autorrevisão, mudanças
retornando ao autor e liberação de dependentes após revisão. Essas decisões
foram programadas, sem chamadas ao modelo: não qualificam autonomia do S6.

## Evidência e problema

A execução 75 do CTO produziu uma observação admissível em cópia descartável,
com testes preservados. O controlador criou a proposta 76 e encaminhou para
revisão 77. Nas rodadas seguintes, inclusive depois da correção de contexto
instalada em `9688d88e`, Lead e CTO continuaram exigindo implementação/Green
antes de permitir a revisão independente dos testes em Red. A proposta 83 ainda
classifica funcionalidade não implementada como infraestrutura por falta de
outra classificação que o agente considere adequada.

As correções anteriores produziram avanços verificáveis, mas não resolveram essa
etapa. Não há evidência de que outra alteração de prompt isolada seja suficiente.
A prova nativa simples já demonstrou que o modelo consegue revisar Red pela
ferramenta real. O experimento atual deve testar a retirada da revisão da
permissão de revisão, sem confundir essa hipótese com sucesso comprovado.

## Mudança de contrato proposta

Somente na recuperação de uma revisão bloqueada, substituir:

`SPIKE CTO → proposta Lead → revisão da proposta CTO → revisão da entrega`

por:

`SPIKE CTO → admissão determinística → revisão independente da entrega`

A admissão já existente continua verificando origem, snapshot, autor, execução,
job real, inventário completo, ausência de erros/skips, testes/configuração
preservados e diferença observada. Ela permite uma revisão; não aprova testes,
código, merge ou release. A avaliação semântica da evidência e dos testes cabe
ao revisor da entrega, podendo pedir mudanças ou escalar um impedimento real.

Não alterar o planejamento inicial da release, revisão de arquitetura ou
autoridade do CEO sobre brief e exceções. Não alterar o modelo.

## Implementação delimitada

1. Criar recibo de autorização de reavaliação do controlador, sem atribuí-lo
   falsamente a Lead/CTO e sem fabricar `plan_review` ou aprovação independente.
2. Usar a transferência nativa de revisão e a substituição já existente do
   trecho pendente do grafo. Reutilizar as rotinas existentes; não criar serviço,
   banco ou orquestrador novo.
3. Vincular a autorização ao projeto/release, handoff original, incidente,
   diagnóstico, observação normalizada e snapshot. Uma mesma autorização não
   cria mais de uma revisão, inclusive após crash entre gravação e handoff.
4. Preservar cards, revisões e sessões antigas. A entrega da cópia experimental
   nunca é promovida a implementação nem usada no lugar do handoff do autor.
5. Selecionar revisor diferente do autor. Aprovação exige a ferramenta de revisão
   atual e o snapshot exato. Mudanças voltam ao autor e invalidam aprovações antigas.
6. Liberar dependentes apenas após a revisão da entrega. Para testes, isso exige
   freeze independente; para implementação, Green, controles negativos e revisão.
7. Proposta histórica não aprovada fica arquivada como substituída pelo contrato
   novo, não marcada como aprovada. Não editar retroativamente suas decisões.
8. Mesma observação recusada não ganha repetição por novo recibo ou reenvio.
   Impedimento real continua visível com dono e próxima ação; sem sucesso fictício.

## Validação antes da ativação

- Rejeitar autoria incorreta, autoaprovação, snapshot alterado, evidência repetida,
  testes enfraquecidos, jobs incompletos e aprovações obsoletas.
- Demonstrar uma única transferência após crash e reconciliações repetidas.
- Demonstrar mudanças → autor → novo handoff → nova revisão independente.
- Demonstrar que dependentes não começam antes do freeze/aprovação correspondente.
- Executar a recuperação real do S6 com o mesmo modelo. Nenhuma implementação
  do produto será escrita pelo operador para fazer o ensaio passar.
- Se a revisão da entrega continuar confundindo Red e Green, registrar a falha
  e reavaliar esse ponto; não acrescentar outra camada de meta-revisão.

## O que permanece obrigatório

TDD, revisão independente dos testes e do código, imutabilidade da entrega,
regressão integral, controles negativos, PR, CI local no SHA exato, deploy,
rollback e QA. `HOMOLOGADA` continua dependente de todos os critérios.

## Motivo do aceite explícito

O plano aprovado e o ADR 0007 exigem uma proposta de sucessão com aprovação
independente antes da nova revisão. Esta proposta remove especificamente essa
aprovação intermediária. Embora mantenha a revisão independente da entrega,
é uma alteração do contrato aprovado e não deve ser ativada implicitamente.
O proprietário concedeu esse aceite na resposta “Aprovar a simplificação delimitada”.

## Ativação e limite da evidência

A ativação preservou a proposta antiga arquivada e transferiu a entrega para
revisão nativa. Um erro de contexto (`submission_contract`) impediu a primeira
execução; foi corrigido, testado e reconstruído offline com o contexto real.
O card retornou à revisão sem nova evidência ou aprovação fabricada. Isso
continua sendo uma retomada assistida; autonomia só pode ser avaliada pelo
resultado posterior dos agentes e dos gates completos.

A aposentadoria usa arquivamento nativo, com cópia durável do workspace,
para impedir que o recuperador trate a proposta substituída como impedimento
ativo. O diagnóstico desnecessário originado por esse bloqueio foi arquivado
após drenagem, sem aprovação de entrega.
