# ADR 0004 — Reparo limitado e correção técnica de testes

Estado: **aceito pelo proprietário em 26/10/2026** ao aprovar os refinamentos e
o plano da [auditoria](EXECUTION-REVIEW-2026-10-26.md). Não aprova retroativamente
o PR 56, seus testes ou QA. A recuperação dessa tentativa será assistida.

## Decisão

O brief aprovado governa as expectativas derivadas. Lead classifica uma falha
de QA; uma proposta corretiva nativa é revisada independentemente pela matriz.
CTO resolve ambiguidades técnicas. O CEO continua responsável por mudança de
escopo e exceção que remova cobertura. Nenhum agente aprova o próprio trabalho.

Uma correção técnica de teste pode gerar uma nova revisão preservando a versão
errada e justificando a mudança pelo brief. Isso não é um novo Red de produto:
o recibo `test_revision` identifica explicitamente o Red histórico, a suíte atual,
a autoridade técnica e o teste corrigido. Revisão, novo freeze, Green, controles
negativos, revisão da entrega, PR, CI e QA continuam obrigatórios.

## Implementação inicial limitada

- Somente o último pacote serializado que teve QA implantado recusado; falha de
  infraestrutura e efeito Docker pendente não acionam reparo de produto.
- Um card corretivo `plan` no Kanban, com classificação, motivo e caminhos QA.
  Não refazer brief ou plano integral. O plano aprovado e seu grafo ficam intactos.
- Um novo pacote de testes/implementação/integração, com base no SHA realmente
  implantado. Não reabrir ou marcar como entregue o card antigo em triagem.
- Para `test_contract`, apenas valores `text` em arquivos QA existentes e
  explicitamente autorizados. Mesmos IDs, ações, seletores, caminhos e arquivos
  Python. O gate verifica essa estrutura; o revisor verifica a semântica.
- A exceção é específica da nova revisão. Trabalho normal continua impedido de
  alterar testes anteriores; a CI só aceita a revisão exatamente congelada.
- Para `product`, os testes anteriores permanecem imutáveis e aplica-se o Red
  de funcionalidade atualmente suportado. Reparo que dependa de um teste existente
  já vermelho aguardará a qualificação do Red de regressão em S5.
- No máximo dois pacotes corretivos nessa cadeia; depois, diagnóstico explícito.
  Não resetar breaker ou gerar infinitos planos iguais.
- Se uma atividade do pacote corretivo chegar à triagem, um diagnóstico CTO
  concluído pode fundamentar a próxima proposta revisada, dentro do mesmo limite
  de dois pacotes. O card triado, seus arquivos e suas tentativas permanecem
  preservados. A nova proposta recebe a falha e o diagnóstico anteriores; não
  retoma o worker que o breaker recusou.
- Somente a visão de aceitação seleciona o pacote substituto. Evidências antigas
  continuam negativas; a homologação exige o commit final e serviço atual saudável.

O marcador `red` em alguns handoffs existentes pode referenciar `test_revision`;
o tipo do recibo distingue as provas. Descrição do PR e contexto do revisor devem
declarar Red histórico e correção técnica, sem alegar execução de Red nova.

## Complexidade e limites posteriores

`repairs.py` concentra esta regra específica e reutiliza cards, revisão de planos,
Store, executor e publicação existentes. A expansão além da meta inicial de linhas
é justificada pela ausência de um caminho pós-QA normal, identificada na auditoria.
Não acrescenta serviço, banco, geração de plano global ou novo motor de workflow.
Não generalizar para correção arbitrária de testes ou replanejamento multi-stack.

O aceite abrange os refinamentos propostos, mas o Red de regressão, o bundle fixado
e a medição financeira completa continuam pendentes de implementação/qualificação.
Não fazem parte da alegação de capacidade deste reparo mínimo.

## Validação

Diagnóstico recebe também o brief e a autoridade corretiva. Em correção de QA,
seu experimento executa suíte e prévia de navegador; recusa não aprova a entrega.
Orientação de retomada não pode exigir escrita fora dos caminhos QA autorizados.

Testes do núcleo verificam exceção restrita, revisão independente, proteção de
testes Python, alvos de controles, não duplicação e preservação do grafo.
`scripts/qualify_qa_correction.py` exercita Docker/Chromium real com dez jobs:
contradição recusada, correção apenas da expectativa autorizada, Green, controles,
revisão, validação integrada e diagnóstico do QA negativo sem aprovação. Decisões dessa fixture são programadas, não julgamento
de modelo ou lifecycle nativo. O resultado da recuperação real é registrado no
status; sua conclusão não qualifica autonomia sem intervenção.
