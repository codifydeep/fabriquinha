# S5 — Impasse recorrente de revisão

Em 26/10/2026, o segundo ciclo começou após aprovação do novo brief Reset/Undo.
Produto usou a decisão histórica; Tech Lead criou dois pacotes dependentes,
revisados pelo CTO. O primeiro Red passou e houve devoluções/correções nativas.
O ciclo repetiu a revisão dos testes sem chegar ao freeze.

O revisor pediu múltiplas entradas AC7 e remoção de AC8. O protocolo aceita um
check por ID de critério, com IDs únicos; o gate exige todos os critérios
atribuídos, incluindo AC8. As sucessoras mudavam o QA JSON sem resolver essas
exigências. A ferramenta permitia ao modelo escalar, mas não o impunha.

A execução foi drenada em 6.857/7.000 chamadas, sem matar requisição em voo ou
modificar testes, aprovações, cards e snapshots. Essa manutenção externa impede
qualificar o ciclo inteiro como autônomo, mesmo que depois entregue o produto.
A primeira qualificação S4 permanece válida pela sua fonte original.

Desde o fim do S4, o contador avançou 46 chamadas, com US$ 0,1736602 reportados:
38 vinculadas à release e oito sem vínculo de atividade. Todas entram no teto
e no custo total. A origem das oito não foi demonstrada; não atribuí-las por
horário nem supor que são compaction sem prova. Não há reset de contador.

## Reparo mínimo

Na terceira devolução independente que ainda aponta os mesmos arquivos, o
controlador promove o parecer atual ao escalonamento existente. Compara os
dois pareceres anteriores validados no Kanban e o atual; não usa texto de chat,
contagem de handoffs ou declaração do autor. Histórico de outro projeto, fase,
contrato, execução ou revisor não autorizado é recusado.

O CTO recebe o parecer atual, referências anteriores e o protocolo real de QA.
Deve executar o experimento permitido e orientar a revisão, ou manter um bloqueio
explícito se nenhuma operação disponível resolver. A repetição nos mesmos arquivos
é sinal de retrabalho, não afirmação de causa idêntica. Não há aprovação automática,
dispensa de testes ou encerramento da versão por contador. Uma aprovação válida
não é promovida a incidente por haver revisões anteriores.

## Qualificação e próxima fronteira

328 testes passaram. `scripts/qualify_hermes_recovery.py --review-churn` executou
13 atividades nativas, 41 respostas locais programadas e três diagnósticos,
com Docker real. Três pareceres `changes` acionaram o CTO sem o modelo pedir
`escalate`; houve SPIKE, retomada da revisão, revalidação e recuperação após
reinício sem duplicar ações. Zero chamadas pagas; decisões programadas não
representam julgamento de modelo.

Aplicar a revisão publicada em manutenção drenada e retomar o mesmo ciclo, sem
resetar história ou pedir novo aceite de negócio. Observar a decisão real do CTO
antes de ampliar o protocolo ou mudar um gate. Resolver limitações como tais,
preservando evidência e distinguindo entrega assistida de autonomia.
