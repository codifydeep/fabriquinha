# S6 — submissão de controles e recuperação limitada

Estado: orientação e continuação qualificadas offline no Hermes nativo.
Fonte `b3b7f6f6` instalada após qualificação offline; proposta sucessora terminou em novo hold. Execução drenada para separar pré-condições e resultados. Não é aprovação de entrega nem autorização para reset.

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
programadas, sem chamadas pagas. Fonte instalada e retomada real iniciada em
7.033/7.064 chamadas, sem aumento de teto. A proposta sucessora foi submetida
pelo Lead ao CTO; seu resultado e a entrega real ainda estão pendentes. O ensaio distingue 11 cards históricos de trabalho dos seis
cards ativos da entrega; o ambiente foi retirado após registrar as evidências.


## Resultado real da revisão 2

A equipe reconheceu corretamente o recibo do CEO e o manifesto congelado. Após
uma devolução, porém, aprovou hold de infraestrutura por exigir que a entrega
substituta já tivesse handoff, controles e Green antes de começar. O próprio
plano reconheceu que as lacunas eram de cobertura e podiam ser resolvidas com
um conjunto completo. Não houve falha de ferramenta observada nessa revisão;
o impedimento foi uma inferência circular sobre a ordem de execução.

O ajuste de contexto separa: início = aceite de negócio, snapshot/freeze íntegros
e revisão do plano; conclusão = Green novo, controles completos, handoff válido
e revisão de entrega. A ausência do handoff antigo não prova defeito de
infraestrutura. Infraestrutura/escopo continuam opções de hold para impedimentos
reais distintos; nenhuma aprovação antiga é reinterpretada nem gate removido.
A decisão da revisão 2 está preservada. O ajuste ainda precisa ser instalado e
uma eventual nova revisão deve ter vínculo explícito com as decisões anteriores;
não repetir chamadas idênticas nem desbloquear a implementação diretamente.


## Aplicação do ajuste de fases — 28/10

A revisão 3 seleciona o predecessor mais recente entre as revisões de contrato
conhecidas. A seleção é fixada pela fonte do controlador; o agente não pode
inventar uma revisão nem gerar outra tentativa idêntica. Propostas pendentes
são aguardadas e aprovações executáveis são reutilizadas. Holds concluídos
permanecem registrados e exigem nova revisão independente.

414 testes passaram. Uma prova direcionada usou cópia SQLite do board real,
recibos e snapshots preservados, com escrita em armazenamento isolado. A primeira
preparação omitiu o pin da instalação e foi corretamente recusada. Com o mesmo
pin copiado, o Hermes criou exatamente uma sucessora ligada ao hold mais recente;
a segunda reconciliação reutilizou o mesmo card. Triagem, holds e board real
permaneceram intactos. Zero chamadas ao modelo. Essa prova cobre a seleção e
criação da nova revisão; o julgamento dos agentes segue pendente.


## Contradição no prompt de sistema — 28/10

A inspeção do adaptador SDK encontrou uma causa adicional que os ajustes de
contexto não cobriam: toda atividade de correção recebia a instrução de sistema
para classificar QA implantado como `product` ou `test_contract`. A ferramenta
da continuação oferecia `submission`, `infrastructure` e `scope`. A orientação
de maior prioridade contradizia a fase e os argumentos permitidos.

O adaptador agora escolhe a instrução pelo tipo de correção. A continuação pede
um plano para iniciar a implementação substituta e situa Green, controles e
handoff como saídas futuras; QA pós-deploy mantém seu contrato próprio. A sessão
de continuação inclui o digest dessa instrução em sua identidade. Sessões antigas
continuam arquivadas; uma retomada comum com a mesma instrução mantém a sessão,
mas a instrução antiga não contamina uma revisão sob o contrato corrigido.
415 testes passaram, incluindo separação dos prompts e continuidade/renovação
da sessão. A proposta real da revisão 3 já foi submetida como `submission`;
sua revisão foi pausada e drenada antes da atualização. Não é necessário criar
outra proposta para testar este reparo. A implementação e a entrega continuam
sem aprovação e dependem do resultado dessa revisão.

## Resultado da retomada — 28/10

A fonte `b72b3f07` foi instalada com o provedor desabilitado e o supervisor
parado; a admissão dos nove perfis e do GitHub passou antes da retomada.
O CTO concluiu a revisão 28 do card `t_b92b0f2c`: aprovou o plano como
`submission`, distinguindo condições de início dos gates de entrega.
O recibo independente `46486aed02e1bea8a830beb3431b44efd411aa6b3b91419ebb45823cba761e60`
autoriza somente a continuação. O controlador materializou o grafo sucessor e
iniciou automaticamente o frontend no card `t_b7e81da1` (execução 29).

Isso comprova o handoff real desta recuperação, não a entrega do S6. A triagem
anterior e os testes congelados permanecem preservados. A nova implementação
continua obrigada a apresentar Green novo, o conjunto completo de controles
negativos, revisão independente, PR, CI, implantação e QA. O segundo incremento
e as validações restantes de autonomia também continuam pendentes. O teto
específico foi mantido em 7.064 chamadas, sem fallback.

## Redução do custo de expressão dos controles — 28/10

A execução 29 confirmou Green, mas encerrou sem handoff após controles
incompletos. O Tech Lead realizou diagnóstico independente e retomou o frontend
na execução 31. Isso demonstra a recuperação desse incidente, sem aprovação da
entrega. A transcrição mostrou anúncios de seis mutações que enviavam apenas
duas: o formato exigia repetir um arquivo de aproximadamente 7,5 KB por controle.

A fonte passa a aceitar, além de conteúdo completo, `{before, after}` por arquivo
em cada mutação. O trecho original deve existir exatamente uma vez no snapshot
Green. Não há regex, shell, alteração do workspace ou acúmulo entre submissões.
Cada mutação continua independente, sujeita à proteção dos testes e à execução
da suíte completa. O conjunto deve cobrir todos os alvos congelados, como antes.

O teste novo falhou antes da implementação; os 416 testes passaram depois,
incluindo ausência/ambiguidade do trecho, formato inválido, tentativa de alterar
teste e preservação do original. A alternativa está validada offline, ainda não
instalada no ensaio ativo; não é evidência de que o agente consegue concluir os
controles ou a entrega.

## Compatibilidade da reconciliação — 28/10

Após a autorização do teto de 8.500 chamadas, a execução 32 retomou o mesmo card.
A reconciliação detectou que o texto explicativo atualizado dos controles mudava
o hash de contexto de uma proposta histórica. A correção preserva o texto do
recibo original ao revalidar uma proposta existente; todos os demais fatos,
vínculos e o corpo do card continuam comparados. Novas propostas recebem a
orientação atual. Não se reescrevem aprovação, contexto histórico ou evidências.
O teste de mudança de orientação falhou antes do reparo e passou depois;
a suíte completa passou com 416 testes. A instalação dessa correção é necessária
para a reconciliação continuar depois da atividade do frontend.

## Controles reais concluídos — 28/10

Com a fonte `c5b54d41`, a reconciliação deixou de apresentar o conflito histórico.
Na execução 33, o frontend submeteu seis mutações (cinco no formato compacto).
O controlador comprovou Green e cobertura dos sete alvos congelados; recibo de
controles `91dc763109ea3e758b373bd7dc6ceea6dc1d742e65598d2141842572cc949951`,
vinculado ao Green `997d9c8ef0e3a883aa5d44bb85a6cac2a275c874569b9d32a2a12cc6c365839f`.
A execução 34 foi despachada automaticamente ao Tech Lead para revisão
independente. Isso qualifica o uso real do formato compacto nesta entrega;
ainda não comprova aprovação, integração, homologação ou autonomia completa.

## Primeiro incremento integrado e validado — 28/10

A revisão independente da implementação foi aprovada. O PR
[codifydeep/descartavel#13](https://github.com/codifydeep/descartavel/pull/13)
passou no status obrigatório `fabriquinha-local-ci` e foi integrado no commit
`2d2b7fb3b987748713e6f691d9c10fde9afd4ad2`. DevOps concluiu candidato, rollback
e restauração; Quality/Security executou QA de navegador na mesma entrega.
O recibo `2d4e24b09859c0294accad2074a1d54ed305b99beda4671966d599094f93c947`
comprova os cinco critérios do primeiro incremento e rollback verificado.

O controlador liberou automaticamente o card de testes `t_3bf2dec1`, execução 41,
para o segundo incremento. O recibo conserva `delivery_approval=false`: o S6
completo exige entrada do segundo participante, limite de dois jogadores,
remoção de salas cheias da disponibilidade e regressões do primeiro incremento.
Canal real, restauração operacional e distribuição também permanecem no plano
maior de qualificação; esse marco não é prova de autonomia completa.

## Limite de saída nas continuações — 28/10

A autoria dos testes do segundo incremento terminou com
`output_budget_exceeds_policy`: após truncamento, a recuperação nativa tentou
32.768 tokens, acima dos 16.384 autorizados. O relay recusou corretamente.
O adaptador agora fixa `max_tokens` também no `request_overrides` suportado pelo
SDK. Não há patch no upstream, aumento de orçamento ou flexibilização do relay.
A atribuição de atividade continua no cabeçalho da requisição.

A suíte passou com 417 testes. Uma prova offline no transporte real do upstream
confirmou que a tentativa de duplicar cada um dos quatro limites suportados
permanece limitada ao valor configurado; sem o override, o transporte reproduziu
a duplicação. Zero chamadas ao modelo nessa prova. Isso valida o teto na
requisição, não a capacidade de terminar uma geração dentro dele. A autoria do
segundo incremento e sua recuperação ainda precisam terminar no fluxo real.

## Diagnóstico da autoria de testes incrementais — 28/10

Lead e CTO interpretaram a suíte antiga verde como impedimento ao Red do segundo
incremento; o hold do CTO chegou a sugerir falhas nos casos congelados anteriores.
Essa decisão permanece como histórico, sem autoridade para enfraquecer testes.
A orientação de diagnóstico foi corrigida: testes antigos verdes são a base de
regressão; a autoria deve acrescentar testes do novo escopo e produzir Red neles.
Retomar a autoria precede Red, enquanto implementação continua bloqueada até
Red real e freeze independente. O erro de limite de saída é uma pré-condição de
transporte separada da ausência de testes novos. Os 38 testes de recuperação
passaram. A reavaliação técnica usará o vínculo de predecessor já existente,
sem novo mecanismo de retry nem edição retroativa do hold.

## Segundo incremento: correção após revisão — 28/10

A execução 45 produziu Red para os sete comportamentos novos, preservando os
nove testes verdes da base. Na execução 46, o Tech Lead pediu mudanças: a
rejeição do terceiro participante estava verificada pela API, mas faltava
comprovar a mensagem visível no navegador. A decisão está vinculada ao recibo
`42d74a76aa57dd29a462a2b9fe85114d5069d08b5b534f157901fbfc2a024ae1`.

O controlador devolveu a autoria ao Quality/Security, execução 47, que submeteu
novo Red (`336be906cd42ea110831a45c99a634cf5b341006bcd453dccadd0d7362ee2203`)
e preservou a suíte anterior verde. A execução 48 foi despachada ao Tech Lead
para nova revisão. Esse retorno ocorreu sem edição manual dos testes ou
aprovação pelo operador. Ainda não comprova aprovação da revisão, Green,
integração ou homologação do segundo incremento.

## Contexto e diagnóstico da segunda implementação — 28/10

A tentativa 51 terminou sem handoff validado após 13 chamadas. O log registra
cinco compactações e bloqueio por compactação ineficaz, acompanhado de releituras.
O CTO, execução 52, preservou o incidente em hold: a suíte ainda mostra nove
casos verdes e sete comportamentos de entrada na sala ausentes. Não há Green
nem evidência de alteração funcional concluída. Esse resultado não autoriza
outra tentativa idêntica ou mudanças nos testes congelados.

A medição do prompt inicial corrige uma interpretação preliminar: cerca de
6.396 caracteres vêm do contexto nativo; o restante dos 53.409 caracteres inclui
contexto estruturado do pacote e diagnóstico. O comentário nativo tem apenas
uma referência DIAG. Portanto, não se deve atribuir o volume a comentários
históricos nem removê-los indiscriminadamente. O experimento anexado contém
11.019 caracteres de relatório, além do veredito e de sua referência durável.

Foi preparado um reparo de observabilidade no adaptador: erros de handoff
incluem contadores numéricos delimitados de compactação e ineficácia, lidos do
compressor nativo fixado. Resumos, respostas e credenciais não são copiados.
Isso fornece evidência ao diagnóstico, sem mudar gates, resetar sessões ou
conceder retries. O teste novo falhou antes do reparo e os 14 testes do adaptador
passaram depois. A instalação e uma correção de contexto ainda precisam ser
qualificadas; esta telemetria isolada não resolve a repetição observada.

## Projeção da continuação revisada — 28/10

O contexto operacional agora pode representar a continuação já revisada por
seus recibos exatos, card de origem e contrato de submissão, em vez de repetir
o plano anterior inteiro e sua recusa histórica de controles. A validação da
proposta e da revisão continua ocorrendo antes dessa projeção. Brief aprovado,
arquitetura, critérios do pacote, baseline e alvos congelados continuam sendo
fornecidos separadamente, sem mudança nas verificações de entrega.

A leitura somente de evidências reais validou a revisão
`46486aed02e1bea8a830beb3431b44efd411aa6b3b91419ebb45823cba761e60`:
o trecho passou de 5.723 para 843 caracteres. Os documentos originais permaneceram
inalterados. Os 17 testes de releases passaram, incluindo preservação de
identificadores/contrato e imutabilidade do documento. Isso é redução de
contexto, não prova de recuperação do modelo; o diagnóstico anexado ainda
precisa ser revisado antes da instalação conjunta e nova tentativa.

## Projeção do diagnóstico e preparação da manutenção — 28/10

A projeção enviada ao agente substitui apenas os inventários repetidos de nomes
de casos por contagem e referência ao recibo completo. Veredito, hipótese,
snapshot, falhas, frames, erros, skips e resultados inesperados permanecem
integrais. A autorização de recuperação usa os dados completos originais, nunca
a projeção de prompt. A prova com o diagnóstico real reduziu 14.223 para 11.364
caracteres e comparou falhas/veredito idênticos; o teste protege também contra
mutação do recibo. A suíte completa passou com 420 testes.

O controlador entrou em manutenção drenada, sem runs abertos, sandboxes
pendentes ou efeitos Docker pendentes. O hold do CTO continua preservado.
Telemetria e as duas projeções serão instaladas conjuntamente; não houve nova
chamada ao modelo para qualificar essas alterações. Redução de aproximadamente
7,7 mil caracteres no prompt observado não prova resolução da repetição.

## Continuação após falha de protocolo — 28/10

A instalação da fonte `3dfe073f` foi preparada sob pausa drenada; doctor verde,
relay parado, política desabilitada, supervisor descarregado. Antes de ativar,
foi identificada outra lacuna: o mecanismo de continuação revisada só admitia
recusa de controles negativos. O hold por `missing_terminal_operation` não tinha
caminho equivalente, mesmo após um reparo técnico no controlador.

O mesmo mecanismo passou a admitir essa falha exata do SDK, sem liberar a
triagem: implementação anterior à revisão, snapshot inalterado, testes
independentemente congelados preservados, ausência de efeitos pendentes e
hold/experimento exatos do CTO continuam obrigatórios. A equipe precisa propor
uma abordagem diferente e obter revisão independente; infraestrutura ou escopo
continuam sendo holds válidos. Não se exige Green antigo para começar a nova
implementação; exige-se Green novo, controles e revisão para concluí-la.
O limite existente de duas continuações permanece, sem reset de card ou breaker.

A admissão somente leitura do incidente real da execução 51 passou e manteve
`delivery_approval=false`; nenhum card foi criado por essa prova. O novo teste
falhou antes do reparo e a suíte completa passou com 421 testes. Ainda falta
instalar essa extensão e validar a proposta/execução real; manutenção continua.

## Janela de contexto: capacidade anunciada e limite instalado — 28/10

A tentativa 55 repetiu o encerramento sem handoff, agora com telemetria:
12 chamadas, três compactações e duas ineficazes. O pedido ativo estava
preservado pelo marcador nativo STILL IN PROGRESS; ferramentas de escrita
estavam disponíveis. Portanto, não há evidência para alterar o protocolo nativo
de preservação da tarefa ou permissões do sandbox.

A consulta pública a [OpenRouter models](https://openrouter.ai/api/v1/models)
retornou `context_length=1000000` para `anthropic/claude-haiku-5.5`. O perfil
instalado limitava o SDK a 65.536. Preparou-se uma janela moderada de 131.072,
sem mudar modelo, saída de 16.384, número de iterações, teto de chamadas ou
fallback. No compressor upstream fixado, o cálculo offline do limiar com reserva
de saída passou de 41.779 para 97.484 tokens. Não é promessa de menor custo:
a hipótese é evitar releituras e resumos repetidos, a medir no fluxo real.

A admissão rejeita o perfil antigo sob a fonte nova; a migração precisa ocorrer
sob manutenção drenada, com backup e atualização explícita do contrato instalado.
Não instalar a configuração durante um worker ativo. Outros modelos só podem ser
qualificados se sua capacidade comportar essa janela; não presumir capacidade
por nome. O teste de rejeição do perfil antigo falhou antes da alteração.

## Validação completa disponível ao implementador — 28/10

Após migrar a janela, a execução 58 alterou `app.py` e terminou sem handoff,
com 11 chamadas e zero compactações/ineficácia. O problema anterior não se
repetiu nessa janela, mas o agente tentou executar a suíte no terminal: rodou
somente dois testes de infraestrutura e procurou o módulo privado de aceitação.
Esse resultado parcial nunca foi aceito como Green.

Foi adicionada `delivery_validate`, somente para implementação, reutilizando
`Quality.green` e o executor completo de snapshots. Não aceita comandos, paths,
claims ou receipt IDs do agente. Não fecha sandbox, não faz handoff, não chama
o callback terminal e não preenche a submissão. Depois de editar novamente,
a validação captura outro snapshot. `delivery_submit` continua executando Green,
controles completos e handoff para revisão independente; nenhuma aprovação vem
da operação nova. Autoria de testes e revisão não recebem essa ferramenta.

O teste novo falhou antes da implementação. Uma prova offline no registro real
do Hermes confirmou chamada da operação sem callback terminal, e a superfície
de revisão a excluiu. Zero chamadas ao modelo nessa prova. Isso ainda não
comprova que o agente real usará o validador corretamente; instalação pendente.

## Instalação do validador e impedimento técnico confirmado — 28/10

A fonte `69583463` foi instalada sob manutenção drenada, sem workers ou efeitos
pendentes. O supervisor foi recarregado e retomado. Doctor aprovou os nove
perfis e GitHub; a janela de contexto e o bundle de validação foram preservados.
O relay confirmou 7.201/8.500 chamadas; nenhuma chamada de inferência foi feita
para instalar a alteração. `delivery_validate` está disponível à próxima
implementação, mas seu uso pelo agente real ainda não foi qualificado.

O SPIKE do CTO executou 16 testes: 14 passaram. Um cenário congelado procura uma
sala cujo apelido aleatório acabou de ser gerado, sem criar essa sala. Isso é
um defeito de preparação do teste, não uma razão para alterar o produto para
satisfazer uma precondição impossível. A revisão anterior não identificou o
problema; Red por si só não prova que a falha corresponde ao comportamento alvo.

O outro cenário falha por erro de console durante rejeição HTTP 409. Ainda não
há autorização técnica para remover essa verificação: a exigência de 409 está
numa chamada HTTP separada e não determina a estratégia da interface. Cabe à
equipe avaliar a implementação e preservar as verificações enquanto isso.

### Próxima alteração, antes de outra tentativa

1. Qualificar a revisão técnica de testes Python prevista em F3 do ADR 0006.
   O suporte JSON legado não serve: atualmente exige baseline Green, condição
   incompatível com o defeito encontrado. Não reutilizar essa evidência como
   se fosse uma nova prova Red.
2. Reutilizar cards nativos de proposta, autoria e revisão independente. Vincular
   a proposta ao incidente, diagnóstico do CTO, freeze e snapshot exatos.
   A proposta deve identificar o caminho e o defeito técnico; mudança de negócio
   ou remoção de cobertura continua exigindo aprovação específica do CEO.
3. Preservar as versões anteriores. A autoria gera novo candidato; a revisão
   confere setup, ação e asserção de cada cenário alterado, mantém os casos e
   publica outro freeze. Não permitir edição pelo revisor, alteração silenciosa
   dos hashes nem reutilização da aprovação antiga.
4. Reexecutar a suíte anterior integral e demonstrar Red comportamental para
   a revisão, seguido de Green e controles negativos sobre a mesma nova entrega.
   Preservar o produto já escrito como ponto de partida, nunca como Green aceito.
5. Substituir somente a cauda não publicada do grafo depois da revisão, com
   recuperação idempotente. Manter o limite/histórico de continuações anterior;
   uma revisão técnica é nova precondição explícita, não reset desse limite.
6. Testar offline negação de revisão obsoleta, mudança de produto na autoria,
   remoção de cenário/assertion, retomada entre freeze e grafo e recusa de entrega
   sem novos controles. Depois executar a correção pela equipe, sem escrever o
   produto manualmente nem aprovar retroativamente a tentativa anterior.

Até essa qualificação, o segundo incremento permanece impedido e visível. O
primeiro incremento implantado continua preservado; a release não foi homologada.

### Preparação offline do comparador de fixture

`test_revision.fixture_snapshot_diff` limita a análise aos caminhos Python de
aceitação existentes propostos e aos snapshots exatos. Recusa alterações em
produto, manifestos, helpers, descoberta, definições e instruções anteriores,
incluindo assertions, seletores e timeouts. Acréscimos elegíveis são preparação
linear por chamadas de métodos e atribuições a variáveis locais novas; não aceita
saída antecipada, controle de fluxo, skip ou reatribuição dos nomes existentes.

Isso é evidência estrutural, não prova de segurança semântica: métodos existentes
podem ter efeitos colaterais. O resultado não cria recibo, freeze, card, exceção
de proteção ou aprovação. O caminho instalado de revisão Python continua
fechado até a integração de proposta independente, novo Red, freeze e substituição
idempotente da cauda do grafo. Não alterar `correction_diff` para aceitar o
resultado isoladamente.

Seis testes offline verificam acréscimos, rejeição de enfraquecimentos estruturais,
paths, descoberta, código alheio e preservação dos snapshots. A simulação do caso
real foi somente em memória: identificou três instruções de preparação, sem
escrever o candidato nem executar código do produto. A autoria real caberá ao
agente de testes. Nenhuma chamada ao modelo nesta preparação.

### Red novo sobre a base publicada — preparação offline

A correção é anterior à publicação do segundo incremento: seus testes novos não
existem na base Git do primeiro incremento. Por isso não é necessário estender o
reparo legado pós-deploy nem criar um tipo adicional de evidência de qualidade.

Foi preparado o caminho de autoria que recebe uma proposta independente do tipo
`fixture`, confere o candidato contra o freeze anterior e executa a base original
novamente. Essa base precisa passar. O candidato corrigido executa Red novo;
precisa preservar integralmente os inventários de casos totais e novos. O recibo
normal `red` registra `fixture_revision` com a proposta e o freeze históricos.
Nenhum Red anterior, SPIKE ou Green incompleto é convertido em evidência nova.

Antes de congelar, o controlador revalida a proveniência, a revisão técnica, os
snapshots e a análise estrutural. Os controles obrigatórios são a união dos alvos
do novo Red com todos os alvos previamente congelados, inclusive riscos extras
que o revisor anterior acrescentou. A nova revisão exige autor, revisor permitido,
release, contrato, inventário e baseline exatos. Green e controles continuam no
fluxo normal posterior de implementação.

A instalação ativa ainda não cria propostas `fixture`: a integração nativa de
proposta, autoria e substituição da cauda do grafo permanece pendente. Os testes
desta etapa isolam a autoridade da proposta para verificar o protocolo de
qualidade; não constituem prova de revisão real por agentes nem de retomada S6.

### Proposta técnica nativa — preparação offline

`Repairs.propose_fixture` prepara um card de proposta do Tech Lead, sem alterar
ou liberar o implementador triado. Requer diagnóstico/experimento exatos do CTO,
freeze concluído, snapshot atual, contrato nativo inalterado, ausência de efeitos
pendentes e vínculo único com o grafo. Somente arquivos de aceitação Python novos,
ausentes da base publicada, entram na lista de caminhos elegíveis. Testes já
publicados não recebem essa exceção.

A proposta usa a revisão independente existente e aceita somente correção de
fixture, impedimento de infraestrutura ou questão de escopo. Uma aprovação é
revalidada contra as evidências originais e o protocolo `unpublished-fixture-1`.
Não dispensa a revisão posterior do candidato de testes. A chave idempotente
preserva o mesmo card em repetições; divergência de corpo ou de origem é recusada.
O contador de continuações anteriores não é alterado. Uma segunda revisão de
fixture sob o mesmo caminho permanece impedida.

A admissão somente leitura com os recibos reais da execução 58 e do diagnóstico
59 passou e retornou os três arquivos novos de aceitação; criou zero cards e
manteve `delivery_approval=false`. Os testes offline cobrem idempotência, revisão
por perfil permitido, divergência de protocolo/origem e recusa de mudanças de
produto/escopo. Ainda falta materializar e reconciliar a cauda revisada do grafo,
qualificar a interrupção nessa transição e instalar o conjunto completo.

### Cauda revisada e preservação do trabalho — preparação offline

A materialização existente foi estendida para a proposta `fixture`, sem outro
motor de workflow. Nessa modalidade, substitui também o card de testes do
incremento afetado, além de implementação/integração e dependentes ainda não
iniciados. Todos nascem bloqueados; somente o grafo completo e durável permite
liberá-los. Preserva cards antigos, prefixo concluído, versão do validador e
`submission_depth`; registra `fixture_depth=1`. Outra revisão pelo mesmo caminho
não é autorizada automaticamente.

A implementação nova começa vazia até o novo freeze. O controlador então cria
um snapshot que preserva o produto da tentativa anterior e incorpora somente os
arquivos de teste da revisão exata. Revalida os testes completos antes de entregar
o workspace. Não sobrescreve o workspace antigo e não importa seu antigo Green.
A repetição da composição produz a mesma identidade. Workers já iniciados continuam
protegidos pela conferência dos testes congelados, sem re-semeadura de trabalho.

Os testes de falha antes/depois da persistência do grafo verificam ausência de
ativação parcial, duplicação de cards e mudança dos cards originais. Também
verificam remapeamento das dependências e preservação da implementação na nova
base. A proposta recebe os fontes completos e hashes do snapshot congelado, até
128 KiB, porque a fase documental não possui acesso a arquivos/terminal; exceder
esse limite é impedimento explícito, nunca truncamento silencioso. As instruções
de sistema e a identidade da sessão distinguem proposta de fixture de reparos
legados e de implementação.

Pendente antes de instalar: qualificação com o Kanban Hermes real numa raiz
isolada, incluindo a criação idempotente e a retomada da transição. Os testes
unitários usam um adaptador de Kanban controlado; não são prova de autonomia.
