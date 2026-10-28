# S6 — submissão de controles e recuperação limitada

Estado: orientação e continuação qualificadas offline no Hermes nativo.
Fonte `a6f59bb8` instalada; a proposta real terminou em hold. Reparo de contexto em manutenção. Não é aprovação de entrega nem autorização para reset.

## Evidência e causa

A equipe executou Red, revisão independente, freeze e Green. Duas atividades de
implementação terminaram em texto, sem operação terminal válida, após recusas
parciais de controles negativos. O Lead fez um experimento e retomou; a repetição
chegou ao CTO e permaneceu em hold. Os gates funcionaram, mas a recuperação não
levou à entrega. Suíte funcional verde não resolve cobertura negativa ausente.

O feedback dizia corrigir os alvos faltantes, sem explicitar que cada submissão
precisa reenviar o conjunto completo. As propostas seguintes substituíam o
conjunto anterior por outro parcial. A cobertura é unida entre mutações da mesma
chamada; chamadas recusadas não acumulam autoridade. O diagnóstico enfatizou o
Green, embora os fatos da recusa negativa estivessem disponíveis.

## Reparo mínimo já implementado em fonte

- Uma orientação compartilhada no tool schema, na recusa e no diagnóstico:
  reenviar todas as mutações úteis juntas; cada uma parte do mesmo snapshot Green.
- Formato explícito: caminho de produto para conteúdo completo substituto;
  nenhuma alteração de teste, configuração ou produto real para simular mutante.
- Experimento Green diagnostica o produto; não comprova os controles negativos.
- Regressão prova que duas submissões parciais continuam recusadas, enquanto o
  conjunto completo satisfaz os mesmos alvos. 402 testes passaram.

Não houve mudança nos alvos, cálculo de cobertura, limites de mutações ou gates.
A fonte instalada e as evidências congeladas continuam preservadas.

## Próxima fronteira — continuação técnica após triagem

Antes de retomar o produto, qualificar uma continuação limitada pela equipe:

1. Reusar a revisão técnica e o mecanismo existente de correção, sem novo daemon
   ou banco. A correção deve distinguir defeito do protocolo de defeito do produto.
2. Preservar triagem e contadores do card anterior. Não reabrir o mesmo card nem
   limpar o breaker. Uma eventual substituição precisa de vínculo explícito,
   justificativa e revisão independente no mesmo grafo/release.
3. Reusar o snapshot e os testes congelados como entrada histórica, nunca como
   Green/controles aprovados da execução nova. Reexecutar os gates e a revisão.
4. Tornar a substituição recuperável e idempotente antes de liberar dependências.
   Recusar duplicação, troca de snapshot/testes e aprovação de revisão obsoleta.
5. O CTO deve produzir orientação sobre a recusa negativa; não basta repetir um
   experimento Green. Não pedir ao CEO uma decisão técnica nem gerar outro brief.
6. Qualificar offline antes de instalar. Somente então permitir que os agentes
   submetam uma nova entrega, conservando a falha como parte do resultado S6.

A admissão somente leitura (`submission_failure`) está implementada: vincula
triagem, execução, decisão/experimento do CTO, recusa negativa, snapshot e freeze
independente. Rejeita divergências e efeitos pendentes; não cria cards nem libera
o breaker. Os vínculos também foram conferidos nas evidências reais preservadas
do S6, sem chamadas ao modelo. A criação idempotente da proposta também está implementada em fonte, ainda
com reconciliação do despacho em fonte: somente Lead, classificação de submissão limitada,
revisão independente do CTO vinculada aos mesmos fatos e nenhuma alteração
do card em triagem. Classificações de infraestrutura/escopo continuam holds.
A substituição do trecho ainda não iniciado está implementada. Ela conserva o
prefixo concluído e o freeze, remapeia as dependências posteriores e só ativa os
novos cards depois de persistir todo o grafo. Interrupções antes e depois dessa
gravação são reexecutadas sem duplicar cards. O limite é de duas continuações
revisadas; esgotá-lo mantém o impedimento, nunca homologa a release.

A reconciliação aguarda conclusão nativa da revisão independente. Recusa mudança
do snapshot, início de trabalho posterior, troca do bundle e tentativa de usar
esta continuação para corrigir uma entrega já implantada. Os cards históricos
permanecem intactos e ligados pelo campo `superseded_cards`; esse vínculo não
significa resolução de incidente. A qualificação nativa ponta a ponta passou. Isso não representa retomada real.
A orientação e a admissão isoladas não fecham essa lacuna de autonomia. A cota adicional aguarda autorização e não foi
aplicada; trabalho offline pode prosseguir sem chamadas ao modelo.


## Resultado da qualificação offline

411 testes do núcleo passaram. A prova nativa completou duas falhas de submissão,
diagnóstico Lead/CTO, proposta do Lead, revisão independente, continuação,
integração de dois incrementos e QA no ambiente implantado. Foram 17 atividades
SDK e 32 chamadas HTTP locais programadas, sem chamadas pagas. Hermes, Docker,
testes, revisão de evidências e implantação foram reais; autores, revisores e
transporte GitHub foram programados. Não é comprovação de julgamento do modelo.

O grafo final usou seis cards de entrega e preservou cinco cards substituídos:
onze cards de trabalho no histórico, além da proposta e dos diagnósticos. O
recibo inicial nomeava os seis cards finais como `generated_work_cards`; esse
rótulo foi corrigido no emissor para distinguir total histórico e grafo ativo.
Os recibos antigos não foram reescritos.

Duas preparações anteriores foram drenadas e preservadas como não qualificadas:
uma mutação idêntica foi rejeitada antes da execução; outra não derrubava teste
algum. A prova aprovada quebrou somente o navegador, deixando a API correta,
para exercitar cobertura parcial real. Os gates não foram modificados.

A fonte publicada foi instalada durante manutenção, passou na admissão dos
nove perfis e o despacho foi retomado sob o teto existente de 7.064, a partir
de 7.029 chamadas. O bundle congelado não mudou. Próximo passo: observar a
continuação executada e revisada pelos agentes reais. Manter
visível a distinção entre incidente histórico e continuação ativa. A prova não
qualifica recuperação genérica de infraestrutura, mudança de escopo ou qualquer
falha após implantação. Canal, restauração e distribuição R4 continuam pendentes.


## Limite encontrado com os agentes reais

A proposta real teve uma devolução e uma revisão aprovada como hold de
infraestrutura. Lead e CTO inferiram que faltava aprovação do CEO porque o
texto preservado do brief ainda dizia “NOT APPROVED”. O recibo de aprovação
exato existe e passou na validação; o documento não precisa ser reescrito nem
aprovado novamente. Não se trata de autorização para ignorar o hold técnico.

A correção em fonte expõe `brief_authority` separadamente do documento: recibo,
revisão, release, decisão, ator e limites. Planejamento, correções e atividades
de entrega passam a receber essa autoridade validada. O contrato esclarece que
rótulos de rascunho são históricos e que o aceite de negócio não dispensa gates.
412 testes passaram, incluindo rascunho contraditório, release divergente e
recusa de aprovação negativa. A proposta que terminou em hold permanece intacta.
Antes de retomar, qualificar uma proposta técnica sucessora vinculada ao contexto
corrigido, com nova revisão independente; não reabrir nem reinterpretar como
aprovação de implementação a decisão anterior.


## Continuação após correção da autoridade do brief

A revisão 2 do contrato de submissão é uma mudança de fonte explicitamente
qualificada, não uma retentativa automática infinita. Uma proposta antiga ainda
em andamento continua sendo aguardada. Uma proposta antiga aprovada para
submissão é reutilizada. Somente um hold concluído e revisado pode receber uma
proposta sucessora ligada como dependência; o recibo e a decisão anteriores
permanecem intactos e são apresentados como contexto histórico.

A nova proposta deve ser revisada independentemente sob a autoridade explícita
do brief. O contexto também apresenta os caminhos e hashes do freeze, sem
permissão de escrita. Propostas antigas continuam legíveis; não recebem outra
classificação nem aprovação retroativa. 414 testes passaram, incluindo criação
idempotente da sucessora, preservação do hold, espera de revisão em curso e
reutilização de uma aprovação já executável. A qualificação nativa desta revisão
passou com dois incrementos, 17 atividades SDK e 32 chamadas HTTP locais
programadas, sem chamadas pagas. Implantação e resultado com agentes reais
ainda pendentes. O ensaio distingue 11 cards históricos de trabalho dos seis
cards ativos da entrega; o ambiente foi retirado após registrar as evidências.
