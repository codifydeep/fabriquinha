# Estado de validação — 2026-10-07

## Inspeção do autor após edição cirúrgica

### Recuperação do artefato salvo sem repetir a edição

O controlador agora mantém checkpoints de falha por **issue e execução**.
O ledger antigo permanece intacto; um checkpoint rejeitado de uma tentativa
anterior não impede a avaliação da nova entrega do autor. Continuam exigidos
identidade nativa, tentativa mais recente, lease fechado, ausência de tarefas
ativas, snapshot congelado e contrato de escopo. Uma rejeição da mesma
execução continua terminal; Red de outra execução não pode ser substituído.

O broker instalado foi atualizado mantendo worker e proxy qualificados. Após
backup SQLite com integridade verificada, o supervisor avaliou o snapshot já
salvo sem uma nova execução de edição. A calibração real passou em 15 casos
positivos e 12 controles negativos. A suíte completa produziu Red com código
de saída 1 e 323 testes executados, vinculado ao mesmo snapshot. O checkpoint registra explicitamente
que a tarefa nativa **não** terminou com sucesso e que a entrega **não** foi
aprovada. A revisão independente do Tech Lead terminou e foi aceita pelo
controlador com `approve_test_revision` no mesmo manifesto. O gate R1 foi
registrado e sua rota de edição foi pausada. Essa aprovação é dos testes
recuperados, não da implementação do produto ou da release. O próximo passo
é a preparação e execução do card dependente R2 sobre esses testes congelados.

A suíte offline dessa mudança executou **2.270 testes, com sete skips
existentes**. Red e calibração não substituem revisão, Green, PR/CI,
implantação e QA. Essa recuperação exigiu correção do operador e, portanto,
não qualifica um novo ciclo integral sem intervenção.

O diagnóstico independente do CTO e do Tech Lead voltou a acionar o autor.
Ele salvou uma correção, mas sua execução nativa terminou como falha: o proxy
misturava leituras anteriores e posteriores à edição, invalidava a cobertura
do arquivo e retornava `review inspection stalled`. Uma comparação somente
leitura dos snapshots preservados verificou que apenas o novo teste mudou,
sem alteração da AST externa ao template. Isso não constitui Red, aprovação
de testes, conclusão da execução nem homologação.

A correção separa a inspeção pré-edição do autor por uma chamada real pareada
com recibo verificado, hash de entrada da autorização, hash de saída distinto,
limite de bytes e preservação dos testes. Todas as fontes devem ter sido lidas
integralmente **antes** dessa chamada. Recibos soltos, replay, IDs duplicados
e leituras posteriores não suprem essa condição. A cobertura de revisão
imutável continua rejeitando versões conflitantes do mesmo arquivo.

A suíte offline executou **2.268 testes, com sete skips existentes**. A imagem
candidata do proxy passou pela validação de requests/respostas V6 e pela
fronteira pós-edição em container sem rede, credenciais ou socket, com zero
chamadas ao modelo. Esse probe usa recibos de fixture, não uma execução
nativa completa do agente. O serviço ativo
não é substituído automaticamente por essa construção. Ainda é necessário
qualificar a recuperação da entrega já salva sem repetir sua edição, executar
calibração, Red e revisão independente e completar PR/CI/deploy/QA. O novo
ciclo continua com intervenção do operador e não comprova autonomia integral.

## Exportação inicial

A suíte offline da implementação ativa executou **1.679 testes, com sete skips existentes**, em container Linux sem rede, chaves ou socket Docker. A verificação de publicação é adicional e procura caminhos privados e padrões de segredos no index do Git, sem imprimir os valores.

Passar esses checks significa que o código preserva sua suíte determinística. Não prova autonomia ponta a ponta, segurança de produção ou instalação portátil completa.

## Último fluxo entregue

`BRIEFSTATUS-1` exerceu dois cards dependentes, revisão congelada, PRs, integração, CI e QA HTTP/browser. A integração frontend está no [PR 45 do repositório descartável](https://github.com/codifydeep/descartavel2/pull/45), commit `e96392f78e4c537ea0d6890ff0eca98bd859958f`. Foram registradas 301 verificações de testes da aplicação, 18 casos HTTP e 48 verificações de browser em dois contextos.

Houve reparos do operador antes da conclusão: não é a prova de um ciclo integral sem intervenção. A entrega é da aplicação descartável, não do Truco.

## Próximo fluxo

`BRIEFDEMO-2` foi preparado para um novo brief e dois cards dependentes. Produto solicitou esclarecimento de negócio sobre como exibir respostas válidas de um modo diferente de `demo`. Em 6 de outubro, o CEO confirmou que toda resposta diferente de `{"mode":"demo"}` deve exibir `Environment unavailable`. A retomada usa um recibo específico da pergunta, sem alterar retroativamente o brief original ou aprovar decisões técnicas. O resultado do novo ciclo ainda precisa ser verificado; não está homologado.

### Retomada com contexto integral

O contexto de implementação e revisão agora pode ser preservado em uma cápsula imutável ligada à rota do controlador. O broker instalado confere seu hash, issue, agente e modo. A retomada da compilação exige correspondência entre código instalado e código validado, cards bloqueados sem assignee e ausência de leases `creating`, `running` ou `closing`. Uma revisão de recuperação já consumida não autoriza repetição idêntica.

A suíte offline atual executou **1.706 testes, com sete skips existentes**. No ensaio `BRIEFDEMO-2`, os testes iniciais do backend tiveram Red registrado e revisão independente aprovada; a implementação terminou e entrou no gate de revisão da entrega. Isso não comprova aprovação final, integração, implantação, QA ou homologação. O ensaio precisou de correção do controlador antes de avançar e não será apresentado como um ciclo integral sem intervenção.

## Evidências públicas e privadas

### Falha de transporte e handoff pré-Red

O autor da correção dos testes recebeu um timeout de 120 segundos do proxy, mas o adaptador ACP antigo retornou fim de turno e o Multica registrou a execução como concluída. Nenhum teste foi alterado nessa execução; a captura de Red recusou corretamente o snapshot inalterado. O diagnóstico completo ultrapassava o limite do handoff e impedia o acionamento do CTO.

O adaptador agora propaga os campos estruturados de falha como erro, sem interpretar frases do modelo ou divulgar a mensagem do provedor. O handoff usa um índice limitado com hash do diagnóstico completo, que continua preservado. A reconciliação pode recuperar esse erro específico de apresentação sem repetir a execução do autor nem conceder aprovação. A imagem corrigida é usada também pelos próximos workers.

A suíte offline executou **1.734 testes, com sete skips existentes**. Um probe isolado executou o guard instalado e verificou falha, limpeza do estado de execução e preservação do histórico, sem chamadas ao modelo; não qualifica o RPC completo. Após a instalação, a reconciliação normal iniciou um diagnóstico independente do CTO. A recuperação do supervisor, os novos testes, a integração frontend e a homologação final ainda não estão comprovados. O ensaio continua com intervenções do operador e não demonstra autonomia integral.

O primeiro diagnóstico foi rejeitado pelo limite de tamanho do contrato tipado. Uma recuperação única, vinculada ao recibo persistente do proxy e à execução independente do CTO, produziu uma decisão válida de correção dos novos testes pelo autor original. O autor foi acionado e depois falhou no gate de leitura `review inspection stalled`; nenhuma entrega ou aprovação foi fabricada. O gate de reentrada do supervisor exige identidade, tarefa nativa, diagnóstico preservado, base original e evidências do predecessor, e recusou a retomada após essa nova falha terminal. A suíte atual executou **1.739 testes, com sete skips existentes**. A recuperação integral e a entrega continuam não comprovadas.

A investigação seguinte observou uma escrita concluída do novo teste e leituras posteriores indicando sua mudança de 51 para 471 linhas. O gate ainda acumulava essas leituras com as da versão anterior e invalidava a inspeção já realizada. A transição pós-escrita agora exige leituras completas anteriores à escrita, conteúdo reconhecível e recibo verificado com tamanho e caminho correspondentes. Ela não se aplica ao modo de reparo obrigatório por patch ou ao modo cirúrgico; não concede Red, revisão ou aprovação. A suíte offline executou **1.741 testes, com sete skips existentes**. O snapshot diagnóstico da execução falhada foi preservado, e o proxy corrigido foi instalado sem reiniciar o autor. A recuperação dessa entrega parcial ainda precisa de qualificação e execução reais.

Um probe somente de leitura verificou todos os bytes e hashes do snapshot parcial, a base protegida intacta e a mudança do novo teste. Também mediu a substituição de três símbolos históricos, sem reinterpretá-la como aprovação. O operador registrou essas evidências e a falha histórica do proxy com proveniência explícita em um diagnóstico único, sem criar Red ou autorizar retry do autor. O CTO produziu uma decisão válida de correção e acionou o autor pelo fluxo normal. A supervisão do filho e a sequência pai retomaram o acompanhamento após conferir tarefas nativas, snapshot, identidade, base, CI e QA do predecessor. A suíte offline executou **1.744 testes, com sete skips existentes**. Esse é um ensaio com intervenção qualificada do operador; ainda faltam a correção concluída, revisão independente e homologação do frontend, além de um ciclo integral sem reparos.

A execução seguinte restaurou os símbolos históricos por patch, mas voltou a falhar no proxy. O ledger demonstrou que streaming e JSON compartilhavam uma identidade de página embora seus hashes de transporte fossem diferentes. As identidades de despacho agora incluem o formato, mantendo os registros antigos intactos. A passagem de fase de revisão de novos testes também reconhece patch concluído após inspeção completa, sem aceitar erro, no-op ou promessa textual. Um probe no histórico privado preservado passou pela reconstrução de fase corrigida sem forçar releitura; isso não qualifica o RPC completo. O novo snapshot foi verificado contra a base e preserva todos os símbolos históricos. Há um único diagnóstico adicional dessa classe, ligado à execução corretiva anterior do CTO, sem resetar o incidente de escrita completa nem autorizar retries automaticamente. A suíte offline executou **1.748 testes, com sete skips existentes**, incluindo o handler para mudança de formato sem chamadas ao modelo. A nova decisão e a entrega continuam sujeitas aos gates normais de Red, revisão, CI e QA.

### Revisão com citação inválida

A primeira entrega de `BRIEFDEMO-2` passou por revisão, CI, merge no [PR 46](https://github.com/codifydeep/descartavel2/pull/46) e QA local no commit `0eec0496ce6a6d7c223a2f776625aec4579b4d41`. O card dependente foi despachado automaticamente nessa base. Sua revisão inicial dos novos testes foi bloqueada corretamente por uma citação que não corresponde à linha observada; esse parecer não foi aceito como aprovação ou rejeição válida.

O controlador pode solicitar uma única revisão nova, somente de leitura, sobre os mesmos testes congelados quando esse erro exato estiver comprovado. O parecer inválido e o estado anterior permanecem preservados. A retomada do supervisor verifica identidade, independência, snapshot e evidências do predecessor, sem concluir a tarefa ou dispensar revisão. Uma nova falha não autoriza repetição infinita.

A nova revisão também citou uma localização inválida e foi escalonada ao CTO sem aceitar nenhum dos pareceres. As decisões agora podem selecionar combinações exatas de arquivo, símbolo, linha e trecho provenientes de leituras completas observadas; o controlador continua validando a evidência congelada e a avaliação semântica permanece independente. A falha de formato do primeiro diagnóstico do CTO foi preservada; uma recuperação limitada com envio tipado produziu um diagnóstico válido solicitando novos testes, não uma aprovação. A criação do card de correção também foi adaptada para gerar uma nova cápsula com o contexto completo e a instrução do CTO, preservando a cápsula anterior. A suíte offline executou **1.728 testes, com sete skips existentes**. A correção dos testes pelo autor, o frontend e a homologação final deste ciclo ainda precisam de evidências; o ciclo continua sem comprovar execução integral sem reparos do operador.

Somente o lock de proveniência das dependências e um fixture público de qualificação do guard permanecem em `team-delivery-kit/evaluation/`. O fixture contém propriedades de isolamento e hashes de imagem, sem conversas, credenciais ou identidades de contas. É uma fotografia de um ensaio sem modelo, não o status atual. Relatórios, diário operacional, transcrições, bases e recibos privados permanecem na instalação original.

Para declarar prontidão, cumprir todos os gates de [ROADMAP.md](ROADMAP.md), incluindo um ciclo novo sem reparos e uma instalação limpa em outro ambiente.
