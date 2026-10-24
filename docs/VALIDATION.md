# Estado de validação — 2026-10-24

## Caminho novo Hermes

[S0/S1](HERMES-S1-QUALIFICATION.md): onze controles nativos/físicos passaram.
[S2 parcial](HERMES-S2-QUALIFICATION.md): onze controles TDD passaram no ciclo
com Docker/HTTP reais e participantes sintéticos; uma prova adicional confirmou
timeout, evidência preservada, retirada e rejeição após reinício. Trinta e um testes
unitários novos passaram. Nenhuma chamada de modelo, instalação ou homologação.
Na suíte histórica atual: 4.523 testes, oito skips preexistentes, nenhuma falha.
A [fatia S3](HERMES-S3-QUALIFICATION.md) passou com Git real, PR/CI simulados,
gate nativo e oitavo job Docker no SHA de merge. PR/merge não foram duplicados
após confirmações perdidas; quatro entradas de CI enganosa foram recusadas.
O total do caminho novo passou a 64 testes. Uma prova posterior com Kanban real
encerrou a claim durante espera, retomou com outro número e observou o mesmo PR
e merge simulados; a claim antiga foi recusada. O prazo de CI também é estável
entre claims nos testes unitários. O revisor principal que escreveu os testes
foi excluído do handoff e outro perfil aprovado recebeu a revisão. Não houve
wakeup automático instalado, modelo, GitHub real ou deploy nessa prova posterior.
A cadeia offline anterior também passou por
build de duas imagens, deploy, rollback/retorno, URL de loopback e QA real de
navegador, com captura arquivada e imagem/commit exatos. As tentativas recusadas
por argumento, rede e transporte de captura foram preservadas; não receberam
aprovação retroativa. Publicação GitHub real, serviço contínuo e autores/revisores
com modelo continuam pendentes. Zero chamadas ao modelo e nenhuma migração.

## Referência atual

O resumo vigente está em [STATUS.md](STATUS.md). O contrato atual é
[qualidade v2](../team-delivery-kit/contracts/quality-lifecycle-v2.md): Red real
→ revisão independente e congelamento dos testes → implementação/Green →
controles negativos obrigatórios → revisão da entrega e gates de publicação.

| Evidência | Resultado e limite |
|---|---|
| Autoria e Red nativos | 381 testes Python, falhas somente no teste novo; 36 Node aprovados, sem erros/skips. Não é aprovação dos testes. |
| Retorno de revisão ao autor | Correção dos testes pelo mesmo autor acionada pelo coordenador. Não qualifica todos os handoffs. |
| Capacidade do proxy | HTTP isolado e ensaio real confirmaram requisição acima de 512 KiB sob o novo limite de 2 MiB. Não aprova revisão. |
| Revisão nativa anterior | Falhou após 40 iterações; 57/71 arquivos integralmente comprovados. Continua preservada, não aprovada. |
| Instalação de referência | Controlador `20261023.36` instalado com execução desligada; worker `20261023.11` preservado. Backup/restauração e dados verificados. Pin migrado com fila/histórico preservados; manutenção selada/drenada, proxy parado e serviço host desabilitado/descarregado. Ativação pendente. |
| Canário físico da candidata de continuação | Hermes/ACP real, 219 páginas/71 arquivos/563.066 bytes; lote de 274.113 caracteres sem spill, controle legado com spill, 157 leituras fora da recomendação e quatro lotes mistos. Uma compactação retirou 64 pares sem perder cobertura. Rejeição sem findings recusada com diagnóstico específico; contrato e hashes preservados. Controle separado obrigou leitura real após promessa prematura com testes novos já lidos. Conjunto: 16 respostas locais, zero externas. Não é aprovação nativa. |
| Recuperação restrita | Registro da condição modificada e despacho de outra revisão pelo coordenador. Não é recuperação integral nem aprovação. |
| Revisão com parada por falta de progresso | Sete chamadas; parada `read_progress_stalled` com 33 iterações restantes; 16/71 arquivos completos. Preservada, sem aprovação. |
| Revisão nativa após a orientação inicial | Despachada pelo coordenador; terminou após seis chamadas, 36 páginas aceitas e 26/71 arquivos completos. Páginas pendentes fora do lote recomendado foram negadas; escalonamento do revisor não foi aceito como parecer completo. `technical_blocked`, sem aprovação. |
| Revisão anterior com spill | 53/71 arquivos completos e 121 páginas aceitas; 33 prévias de spill e quatro deduplicações sem conteúdo não contam como inspeção. Seis chamadas; sem aprovação. |
| Revisão terminal com inspeção completa | **71/71 arquivos completos**, comprovados no controlador. Parecer rejeitado: tentativa de `request_changes` sem findings concretos e dependência circular com gates posteriores. `completed` nativo, `technical_blocked` no controlador; sem congelamento, Green ou homologação. |
| Revisão sucessora terminal | 46/71 arquivos, 80 páginas, seis chamadas; duas promessas em prosa, sem novas leituras, com 35 iterações restantes. `technical_blocked`, sem aprovação. |
| Último ensaio após controle de continuação | **71/71 arquivos e 171 páginas** comprovados no controlador. Primeiro parecer `invalid_json`, feedback com 33 iterações restantes; chamada seguinte HTTP 402. Nativo `failed`, equipe `technical_blocked`, sem congelamento ou aprovação. |
| Última suíte completa registrada | **4.522 executados: 4.514 aprovados, oito skips preexistentes, sem falhas.** Conjunto focado de handoff/validação/linhagem: 60; parecer/atestação/worker/leituras: 34; despacho/coordenação/fontes da imagem: 37. Os novos testes não substituem nem removem os anteriores. |
| Recuperação de pagamento em fixture Linux | Oito consultas HTTP locais, zero ao provedor real e zero ao modelo. Confirmação obrigatória, saldo zero recusado, chave sem limite explícito, contador preservado, locks, leitura do resultado sem repetição e conclusão parcial sem repetir HTTP. Não comprova crédito real ou retomada nativa. |
| Isolamento do canário de pagamento | UID 10000, rede externa indisponível, raiz somente leitura, sem chave real ou socket Docker; `/opt/data` temporário explícito para não criar volume anônimo herdado da imagem. Auxiliar retirado após preservar o recibo. |
| Recuperação de confirmação perdida | Um erro ao salvar o recibo final do qualificador foi reproduzido por regressão e corrigido. A observação do mesmo resultado preservado concluiu o recibo sem executar outro canário. Não é prova de recuperação completa da equipe. |
| Remediação real do provedor | Não executada; confirmação humana, consulta real e registro da recuperação ainda pendentes. A pausa e o contador 6.291/10.000 permanecem preservados. |
| Política final da entrega | Implementação em fonte e seis testes sintéticos, não instalada nem conectada ao despacho. Não qualifica a ponte após Green ou a publicação. |
| Executor da revisão final | Suíte da fixture reexecutada no contêiner dedicado, com tarefa distinta e mesmos testes, manifesto e commit. Dez testes focados; cinco pedidos inválidos recusados no canário físico. Não autentica task nativa ou recibo de job e não aceita parecer. Ainda não conectado ao controlador. |
| Isolamento do executor final | UID 10000, rede none, sem credenciais ou socket; base/snapshot somente leitura e tentativas de escrita negadas. Auxiliar retirado. Duas falhas anteriores da fixture de rede foram preservadas e corrigidas sem alterar o isolamento exigido. |
| Handoff/admissão final em fonte | Registros de copy/Green/sensibilidade e contexto conferidos; intenção persistida, capacidade/prazos fixos, confirmação perdida observada sem novo POST. Tarefa/revisor/workspace/runtime/wakeup/SHA divergentes recusados. Fixtures nativas/SQLite; não instalado ou despachado. |
| Validação final vinculada ao controlador em fonte | Job fixo ligado à admissão e ao recibo persistente exatos; resultados parciais, de outro pedido/SHA ou sem registro recusados. Verificação da origem antes/depois; prazos e incidentes persistentes. Não é revisão nativa ou autorização de merge. |
| Histórico de correções do autor | Regressão reproduzida: a captura rejeitava execuções legítimas já reconhecidas pela admissão. O filtro de linhagem autenticada foi aplicado; registros ausentes/divergentes e tarefas desconhecidas continuam bloqueados. Correção em fonte, ainda não instalada. |
| Reserva antes da admissão | Duas regressões reproduzidas: intenção nativa pendente não reservava o perfil, e a transição não reconferia capacidade sob o lock compartilhado. Corrigidas com reservas e checagem transacional; ainda não qualificam concorrência ponta a ponta entre todas as fases. |
| Recuperação e autonomia completas | Ainda não qualificadas sob o contrato v2. |
| Diagnóstico real de crédito/chave | Somente metadados oficiais, ambos HTTP 200 e disponíveis. Contador/pausa bit a bit preservados; proxy desligado ao final, zero chamadas ao modelo. Não estabelece a causa do 402 ou autoriza retomada. |
| Adaptador final em fonte | Recibo da suíte reautenticado antes do worker; snapshot único somente leitura, rede interna do proxy e nenhuma chave de infraestrutura. Handlers negam escrita e shell. Fixtures offline; sem instalação, roteamento ou parecer nativo. |
| Parecer final e atestação em fonte | Esquema exato, hashes da entrega/validação, critérios e citações reais. Conclusão nativa, lease fechado, política inspecionada e leituras do próprio stream obrigatórios. Recibo durável não autoriza merge; mudanças apontam ao autor, incidentes ao CTO. Não instalado/qualificado nativamente. |
| Diário da fase final | Regressão real reproduzida e corrigida: arquivos vazios não eram preservados e vigorava limite legado de 128 páginas. A fase autenticada agora usa 512 páginas, isolada da revisão dos testes. |
| Correção e coordenador em fonte | Handoff ao implementador original com candidato rejeitado/testes congelados; achados nos testes ficam com CTO. Intenção antes do wakeup, reservas e prazos fixos. Um tick atravessou a revisão e chegou a `awaiting_publication` em fixture; não homologa. Admissão/execução da correção e publicação ainda faltam. |
| Candidata Docker `20261024.37` | Compilação/importação com execução desligada aprovadas, sem rede de build e sem instalação. Os dois Dockerfiles agora incluem as dependências da nova ponte. Não é qualificação nativa ou prova de execução ponta a ponta. |

A falha anterior expôs o caminho só de ferramentas, sem resposta prematura que
inicializasse a fila. A versão atual cobre esse caminho desde a primeira chamada.
A nova fixture mede leituras reais e compactação real, preservando os controles
de aprovação integral e rejeição fundamentada. O parecer nativo aceito permanece pendente;
o bloqueio anterior não foi convertido em sucesso ou defeito funcional do produto.
A prova nativa subsequente expôs outra fronteira: o lote recomendado também
restringia indevidamente páginas legítimas ainda pendentes. O modelo interpretou
essas negações como falta de acesso. Uma candidata separa os dois conceitos,
sem admitir repetição, EOF ou caminhos não registrados. Ela passou no canário
físico e foi instalada; a revisão posterior exercitou a leitura, não aprovou os testes.

O ensaio seguinte revelou spill por orçamento agregado, apesar da isenção de
`read_file` por resultado. A nova prova usa lotes de até 64 páginas, superiores
ao limiar de 200 mil caracteres; lotes de 16 páginas não exercitavam esse caso.
O hook qualificado preserva páginas completas sob o teto já existente de 8 MiB
do diário apenas na revisão autenticada. Outros modos, corpo do proxy, limites
de leitura, permissões e número de iterações não mudaram. Nenhuma prévia antiga
é promovida a recibo; a sucessora precisa produzir suas próprias leituras.

Os testes focados e a suíte completa acima foram executados para esta correção. O controle
físico do fim do orçamento usa uma iteração; a fábrica ACP continua em 40.
Escala e compactação passaram no perfil de respostas fixas, não em toda
estratégia possível do modelo. A memória desse diário é local à execução.

A mudança foi instalada com execução desligada, recuperada por condição
modificada e ativada sob manutenção antes da liberação. Nenhuma leitura ou
aprovação foi herdada da tentativa anterior. A sucessora comprovou a inspeção
integral dos 71 arquivos, mas não uma decisão válida. Três tentativas prévias
continham prosa; a quarta tinha JSON e hashes correspondentes, porém combinava
`request_changes` com `findings=[]`. O encerramento estruturado não passou como
parecer. O validador não extraiu aprovação nem inventou achados.

A justificativa condicionava a revisão dos testes a Green, controles negativos
e aprovação adicional do CTO. Green e controles negativos vêm depois do
congelamento; o contrato não impõe essa aprovação adicional do CTO como
pré-condição. A apresentação da fase a cada chamada e o diagnóstico específico
passaram no canário Hermes/ACP, foram instalados sob manutenção e originaram
uma recuperação por condição modificada. O modo JSON final só restringe a
sintaxe; não fornece aprovação ou substitui os gates locais. A leitura completa
anterior não foi herdada pela nova execução. A equipe ainda precisa concluir
a revisão e toda a cadeia posterior sob o contrato v2.

Depois da revisão terminal, a manutenção foi selada/drenada para a troca.
O proxy ficou desligado durante a qualificação offline; foi reativado com
6.276/10.000 chamadas e 3.724 restantes antes de liberar a manutenção e observar
o despacho nativo pelo coordenador. Essa tentativa terminou bloqueada após seis
chamadas, elevando o contador a 6.282/10.000. A instância foi selada/drenada e
o proxy parado para qualificar a continuação por leitura real. O contador não
foi resetado. Essa correção foi instalada e ativada; o mesmo proxy foi iniciado
e a manutenção liberada após conferência, para despacho pelo coordenador. São estados
independentes: uma task `completed`, uma lease fechada e uma revisão aprovada
não são equivalentes. Confirme o estado vivo antes de agir. Nenhum resultado
histórico abaixo substitui esse diagnóstico.

A última execução terminou depois em falha por pagamento, com inspeção integral
real, mas sem parecer aceito. O contador chegou a 6.291/10.000; o proxy entrou
em pausa persistente e foi parado após selar/drenar a instância. Não houve
aprovação a partir do parecer rejeitado ou das leituras completas. A recuperação
de crédito e sua retomada específica continuam pendentes; a rota de inspeção
incompleta não se aplica a esse caso.

### Recuperação de pagamento: prova isolada versus prova real

A nova rota está instalada, mas desligada para execução. O contrato vincula o
evento HTTP 402 original à execução nativa que falhou, ao proxy exato, ao código
qualificado e ao contador. O registro exige duas qualificações na manutenção
corrente: worker de revisão e canário físico de pagamento. Não cria tarefa,
grant, parecer ou autorização de merge; apenas prepara uma revisão sucessora
para despacho posterior pelo coordenador.

Os testes cobrem rejeição de prova obsoleta ou de outro pedido, contador
divergente, proxy ainda ativo durante o registro, mistura com outra rota e
tentativa de rearmar a mesma condição sob outro identificador. Cobrem também
que as leituras completas da tentativa anterior não suprem a inspeção da nova.
O prazo da prova de remediação é 15 minutos; a fixture não substitui essa prova.

A confirmação do operador precede efeitos. A consulta real, quando autorizada,
é restrita aos endpoints oficiais de crédito e chave, dentro do proxy que já
possui a credencial. Não compra crédito, altera limites ou chama o modelo.
Após resposta incerta, observa-se o recibo original e o lock; uma conclusão
parcial exige prova positiva preservada e não repete a consulta. O registro
posterior exige o mesmo proxy parado e mantém a falha histórica.

Nada disso foi executado com crédito real nesta qualificação. Também não
comprova escalonamento financeiro autônomo, um novo parecer aceito, Green,
PR/CI, implantação, QA ou rollback. O serviço host continua descarregado e a
o pin da nova imagem foi migrado sem iniciar o serviço. A ativação continua separada e pendente.

### Executor final: prova física não é parecer independente

O novo job não recicla Green: executa novamente a suíte completa contra o mesmo
snapshot e confere contagem, hashes congelados e SHA. Rejeita perfil do autor,
tarefa de uma fase anterior, manifesto obsoleto, evidência faltante e pedidos
de comandos ou seleção de testes. Sua saída mantém explicitamente falsas a
autenticação nativa, a verificação do recibo e as autorizações de testes/merge/entrega.

O canário inicial assumia que `network=none` implicava somente um nome de
interface. O kernel também expôs túneis padrão inativos; a consulta comprovou
ausência de rotas externas. A fixture corrigida exige somente loopback ativo
e nenhuma rota por outra interface, além de manter a configuração Docker none.
Os controles negativos recusam interface externa ativa ou rota não local.
Esse diagnóstico não alterou as permissões da entrega ou do contêiner.

Admissão e autenticação do recibo no controlador foram implementadas depois em
fonte, seguidas por worker/transporte, parser e atestação do parecer. A prova
atual usa fixtures nativas/SQLite/jobs. O despacho e a continuação foram ligados
em fonte; faltam admissão/execução da correção, publicação e qualificação
nativa. Não há revisão da entrega aprovada, PR/CI ou homologação a partir dessas fixtures.

## Evidências históricas — não representam o estado vivo

As seções seguintes preservam resultados e limitações de etapas anteriores,
principalmente de 7 de outubro. Expressões como “atual” e “próximo” nessas
seções referem-se àquela etapa, não à execução corrente. Contagens históricas
não devem ser somadas nem apresentadas como execução da suíte de hoje.

## Inspeção do autor após edição cirúrgica

### Contexto e permissões do card dependente R2

A preparação do R2 encontrou dois impedimentos anteriores ao despacho: a
cápsula repetia instruções históricas de fase e excedia seu limite; em seguida,
a validação confundia os caminhos graváveis do R2 original com os caminhos
de leitura do reparo R1. O controlador agora extrai integralmente os dados do
brief e da revisão apenas de um wrapper autenticado de emenda, mantém a
cápsula anterior imutável e registra seu hash. Dados arbitrários, incompletos
ou com conteúdo residual não podem ser extraídos, e o limite não foi ampliado.

No cenário de emenda, a rota original continua gravável somente nos arquivos
do produto. Os testes congelados são entradas de leitura, não novas permissões
de escrita. Recuperações específicas preservam cada impedimento, exigem R1
aprovado, base qualificada, identidade e contrato atuais, ausência de execução
ativa e nenhuma rota R2 já registrada. Reabrir a preparação não concede
despacho, merge ou homologação. As duas correções foram instaladas após backup
SQLite verificado. A suíte offline executou **2.275 testes, com sete skips
existentes**; a continuidade nativa do R2 ainda precisa ser comprovada.

O R2 foi registrado com referência validada ao Red aprovado e seu contexto
nativo foi publicado. A admissão mantinha um bloqueio antigo de dependência
mesmo após a resolução dos impedimentos. A recuperação agora preserva esse
incidente no ledger e só retoma a cadeia já autorizada quando R1 está aprovado,
R2 está registrado e não existem impedimentos dependentes. Binding, aprovação
nativa, orçamento, capacidade e contexto continuam revalidados antes da
ativação; pausas de fases já admitidas e outros bloqueios não são removidos.
A versão instalada passou por **2.277 testes, com sete skips existentes**.
Isso ainda não prova Green, revisão do produto, PR/CI ou homologação do R2.

A consulta de status foi corrigida para distinguir admissões históricas da
cadeia atual pela dependência explícita entre issues. Ela revalida o hash do
contrato, exige uma única cadeia conectada e rejeita ciclos ou ramificações
ambíguas; não escolhe por horário nem por aparência de sucesso. A consulta
real identificou R2 na instalação corrente. A suíte offline executou **2.279
testes, com sete skips existentes**. Metadados de status continuam sem poder
de execução ou aprovação. O autor R2 terminou sua execução nativa; os gates
do controlador e da revisão independente precisam ser verificados separados.

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
