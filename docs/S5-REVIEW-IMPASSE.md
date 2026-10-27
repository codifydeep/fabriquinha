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

O guard foi instalado e acionou o CTO no ensaio real. Ele executou um SPIKE e
manteve `hold`: confundiu a proibição de escrever testes na fase de diagnóstico
com uma proibição de o autor corrigir seus novos candidatos antes do freeze.
O texto “não reescrever QA existente” não distinguia esses candidatos da base.

A clarificação fornece caminhos da base protegida e caminhos presentes somente
na entrega candidata, derivados do Red exato. O autor pode corrigir apenas os
novos caminhos, seguido de outra revisão; revisor e diagnóstico continuam sem
escrita. A cobertura é avaliada pela suíte completa e QA retido/novo em conjunto,
sem pedir IDs duplicados. O DSL, seus checks e os testes antigos não mudam.

Uma orientação técnica realmente aplicada delimita a próxima janela de
recorrência pelo número do seu run nativo. As devoluções antigas continuam no
histórico, mas não são contadas como tentativas sob a orientação nova. Retries,
triagem, breaker e evidências não são zerados. A retomada já abre contexto SDK
novo pelo recibo de orientação existente; não foi criado outro motor de memória.

O mesmo ensaio descartável de 13 atividades passou também com esse contexto:
o CTO distinguiu o teste antigo protegido do candidato novo. Seu `hold` real
permanece preservado. O próximo atendimento deve seguir a decisão técnica
registrada e a clarificação instalada, com novo experimento e revisão, sem
desbloquear diretamente o card ou converter manutenção em autonomia.

333 testes passaram. `scripts/qualify_hermes_recovery.py --review-churn` executou
13 atividades nativas, 41 respostas locais programadas e três diagnósticos,
com Docker real. Três pareceres `changes` acionaram o CTO sem o modelo pedir
`escalate`; houve SPIKE, retomada da revisão, revalidação e recuperação após
reinício sem duplicar ações. Zero chamadas pagas; decisões programadas não
representam julgamento de modelo.

Aplicar a revisão publicada em manutenção drenada e retomar o mesmo ciclo, sem
resetar história ou pedir novo aceite de negócio. Observar a decisão real do CTO
antes de ampliar o protocolo ou mudar um gate. Resolver limitações como tais,
preservando evidência e distinguindo entrega assistida de autonomia.

## Identidade da continuação técnica

O Lead reconheceu a distinção de caminhos, mas encaminhou a questão restante ao
CTO. O encaminhamento reutilizou o CTO antigo em `hold`: a chave de criação não
incluía o predecessor. Assim, idempotência confundia repetir uma solicitação com
uma solicitação técnica nova.

A chave sucessora agora inclui o predecessor nativo concluído e do mesmo
incidente. Uma repetição desse predecessor reutiliza a tarefa; outro predecessor
cria outro atendimento. Chaves antigas são reutilizadas quando já correspondem
ao mesmo predecessor. Nenhum diagnóstico ou veredito antigo é reescrito.
O status segue a cadeia de atendimento atual, inclusive Lead após CTO, em vez
de manter prioridade fixa no diagnóstico antigo.

`scripts/qualify_diagnostic_successors.py` comprovou no Kanban real: novo CTO após
novo encaminhamento, ausência de duplicação após reinício, compatibilidade de
chave anterior e status do sucessor atual. Decisões são fixtures programadas;
zero modelo, zero Docker e nenhum claim aberto. Isso não aprova a entrega S5.

## Operação proibida não é falha de infraestrutura

O novo CTO recebeu a orientação, mas manteve `hold` porque seu SPIKE tentou
substituir testes e foi corretamente recusado, sem produzir experimento. A
recusa genérica não indicava o caminho permitido. Agora ela registra
`diagnostic_refusal`, classificação `operation_forbidden`, fase, caminhos e
próxima operação: `diagnostic_validate` somente com hipótese, sem substituições.
Essa observação da suíte imutável pode permanecer Red e fundamentar orientação;
não concede Green, freeze, aprovação ou permissão para escrever testes.

O diagnóstico também recebe os critérios realmente atribuídos ao card: não pode
aconselhar remover um ID obrigatório do QA. Sua cobertura é composta pela suíte
completa e QA retido/novo. As regras de execução e o DSL não foram afrouxados.

A prova nativa de 13 atividades confirmou: recusa real, mensagem com próximo
passo, observação imutável Red sem erros e retomada da revisão. Outra prova com
Git/Docker confirmou regressão com falhas `subTest` múltiplas no mesmo caso:
preserva-se a multiplicidade das falhas de base/Red/CI, sem duplicar casos ou
ignorar falhas. Todas essas qualificações usaram decisões programadas e zero
chamadas pagas. Retomar somente após publicar e instalar o lote qualificado.
