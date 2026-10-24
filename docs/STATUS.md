# Status do projeto — 24 de outubro de 2026

**Estratégia atual:** plano de simplificação aprovado, com [S0/S1 concluídos](HERMES-S1-QUALIFICATION.md).
A fronteira Hermes + Kanban passou na prova nativa/Docker sem modelo e sem
patches upstream. Próxima etapa: S2/S3, uma pequena cadeia de qualidade/entrega.
O runtime anterior continua pausado. As estimativas e detalhes abaixo descrevem
esse investimento anterior, não uma porcentagem de conclusão da nova arquitetura.

**Experimental. Autonomia completa ainda não qualificada.** Este é um resumo
datado da instalação de referência, não uma consulta de estado vivo nem uma
garantia de funcionamento em outra instalação. Evidências operacionais,
conversas, credenciais, snapshots e bancos permanecem privados.

## Objetivo e critério de conclusão

Receber um brief, refiná-lo com Produto, obter aprovação de negócio e entregar
software em homologação por uma equipe de agentes: planejamento, cards
dependentes, TDD, revisão independente, PR/CI e implantação/QA/rollback no mesmo
commit. O operador não deve precisar dirigir handoffs ou reparar cada etapa.

O único sucesso terminal da release é `HOMOLOGADA`, com evidências verificáveis.
Um worker ativo, teste offline verde ou bloqueio corretamente detectado não
substitui esse resultado. O Truco permanece fora da execução de produto até a
qualificação da equipe. Temporal não está implementado como motor do runtime.

## Estimativa de prontidão

| Área | Estimativa |
|---|---:|
| Infraestrutura, isolamento e controle de acesso | 90% |
| TDD, proteção de testes e revisão imutável | 80% |
| Coordenação e handoffs autônomos | 65% |
| Recuperação de falhas sem intervenção do operador | 60% |
| Instalação reutilizável e qualificação completa | 55% |
| **Consolidado** | **70%** |

São estimativas de engenharia, não cobertura de testes, taxa de sucesso, SLA ou
comprovação de autonomia. Não resultam de um índice automatizado. Não comparar
estimativas históricas como uma série de medições com metodologia constante.
Os critérios objetivos continuam em [ROADMAP.md](ROADMAP.md).
As estimativas foram mantidas nesta atualização: a inspeção de 71/71 arquivos
e a recuperação de pagamento qualificada com fixture não comprovam decisão
válida nem autonomia ponta a ponta.

## O que foi comprovado e o que não foi

- Há fluxos históricos descartáveis com revisão, PR/CI e QA no mesmo commit,
  mas com reparos do operador. Eles não qualificam um novo ciclo sem intervenção
  nem transferem aprovação para o contrato de qualidade atual.
- O controlador de qualidade v2 está instalado para qualificação controlada,
  com isolamento de fases, snapshot imutável e autorização por execução.
- O autor real produziu Red: 381 testes Python executados, falhas de asserção
  restritas ao teste novo, e 36 testes Node aprovados, sem erros ou skips.
- O coordenador devolveu uma solicitação de mudanças ao mesmo autor, que
  corrigiu os testes. Isso comprova esse handoff, não a cadeia completa.
- O proxy com limite de requisição de 2 MiB foi qualificado e instalado sem
  zerar o contador de chamadas. O ensaio seguinte ultrapassou o antigo limite
  de 512 KiB sem aquela rejeição de tamanho.
- O diário de leituras, a captura no loop, o enforcement e as paradas
  estruturadas foram qualificados e instalados. A troca preservou dados e
  configurações, com backup compactado e restauração verificados. O serviço
  host foi migrado naquele ciclo sem resetar fila ou histórico. A troca mais
  recente também teve seu pin migrado, mantendo o serviço parado.
- A revisão anterior consumiu sete chamadas e terminou com diagnóstico `read_progress_stalled`:
  16 dos 71 arquivos tiveram leitura integral comprovada. O controlador manteve
  `technical_blocked`, sem aceitar o diagnóstico como parecer ou aprovação.
- A orientação desde a primeira chamada foi corrigida, qualificada em Hermes
  real e instalada. Uma nova recuperação preservou esse bloqueio; o coordenador
  despachou outra revisão. Ela terminou após seis chamadas e 36 páginas aceitas,
  com 26/71 arquivos completos. O revisor reportou negações de páginas pendentes
  fora do lote recomendado; o controlador manteve `technical_blocked`.
- A revisão seguinte confirmou o uso de lotes, mas terminou com 53/71 arquivos
  completos. O transporte preservou 121 páginas; houve 33 prévias de spill e
  quatro respostas de deduplicação sem conteúdo. Elas não contaram como
  inspeção. Essa é uma tentativa anterior, não o bloqueio mais recente.
- Após a instalação do orçamento agregado restrito à revisão, a sucessora
  comprovou **71/71 arquivos** no transporte do controlador. Terminou nativamente
  em `completed`, mas o controlador manteve `technical_blocked` por parecer
  inválido. Leitura completa não foi convertida em aprovação.
- A última suíte offline registrada executou **4.522 testes: 4.514 aprovados e
  oito skips preexistentes**, sem falhas. O conjunto focado de recuperação
  executou 50 testes, também sem falhas. Aos 27 testes novos de recuperação
  somaram-se dez do executor final/rede, sem retirar ou enfraquecer os anteriores.
  Foram acrescentados depois 31 testes de handoff, admissão, vínculo do job,
  reservas de capacidade e linhagem; o conjunto focado relacionado executou 60
  testes, sem falhas.
  Mais 12 testes cobrem diagnóstico somente leitura, fase de ferramentas e
  adaptador final; o conjunto focado dessas três áreas executou 24, sem falhas.
  Outros 19 cobrem parser/atestação final e a regressão do diário; o conjunto
  focado de parecer, atestação, worker e leituras executou 34, sem falhas.
  Mais 18 cobrem despacho de correção, avanço do coordenador e fontes da imagem;
  o conjunto focado com as regressões do coordenador executou 37, sem falhas.
  Essas provas não substituem a qualificação nativa.
- A tentativa após o ajuste da fase terminou com 46/71 arquivos completos,
  80 páginas preservadas e duas respostas prematuras em prosa. Restavam 35
  iterações; o agente prometeu ler depois em vez de executar as páginas. O
  controlador manteve o bloqueio, sem congelar os testes.
- A revisão após o controle de continuação comprovou **71/71 arquivos e 171
  páginas** no controlador. Seu primeiro parecer final foi rejeitado como
  `invalid_json`; na chamada de continuação, o provedor retornou HTTP 402.
  A execução nativa terminou como `failed`, com bloqueio técnico preservado,
  sem parecer aceito. O proxy entrou em pausa persistente por pagamento.
- A recuperação específica de pagamento foi implementada e instalada no
  controlador com execução desligada. O canário Linux descartável comprovou
  confirmação obrigatória, rejeição de saldo zero, preservação do
  contador, locks e observação de efeito incerto, incluindo conclusão parcial
  sem repetir consultas. Usou oito requisições HTTP à fixture local, zero ao
  provedor real e zero ao modelo. Não verificou o crédito da instalação.
- O pin do scheduler foi migrado para o controlador instalado, preservando
  fila, estado de falhas e históricos dos candidatos. O serviço continua
  desabilitado/descarregado; a manutenção permanece selada e drenada.
- O executor fixo da revisão da entrega reexecutou a suíte de uma fixture em
  Docker sem rede externa, chave ou socket, com base e snapshot somente leitura.
  As tentativas de escrita foram negadas e cinco pedidos inválidos recusados.
  Essa prova ainda não contém admissão nativa, parecer ou autorização de merge.

Não houve congelamento dos testes, Green ou homologação nessa linhagem v2.

## Bloqueios preservados: decisão da fase e conclusão prematura

A revisão anterior completou a inspeção integral. Antes de parar, o worker
produziu três tentativas com prosa fora do contrato e uma tentativa JSON com
`action=request_changes`, hashes correspondentes e `findings=[]`. O contrato
exige achados concretos para solicitar mudanças; um objeto JSON bem formado
não basta. O resultado terminal foi um diagnóstico, não um parecer aceito.

A justificativa dessa última tentativa condicionava a aprovação dos testes a
Green, controles negativos e uma aprovação adicional do CTO. Isso inverte o
contrato vigente: os testes são revisados e congelados **antes** da implementação
e de Green. Aprovar os testes não aprova implementação, merge ou release.
Decisões técnicas continuam com a equipe, sem repassar essa questão ao CEO.

A correção qualificada e instalada explicita essa fronteira em cada chamada,
inclusive após compactação, e devolve erros de contrato específicos sem
afrouxar o validador. Na decisão após inspeção completa, o pedido não oferece
ferramentas e usa modo JSON somente para sintaxe; o parser local e os gates do
controlador continuam obrigatórios. Isso não resolve por si só o julgamento
semântico. Outra execução exige mudança qualificada;
não se deve extrair aprovação da prosa, inventar findings ou repetir o mesmo
perfil. A sucessora expôs uma fronteira anterior: depois de ler os testes novos,
o modo automático ainda permitia duas promessas em prosa sem executar leituras.
Sua falha com 46/71 arquivos permanece preservada.

A correção seguinte, já qualificada offline, no Hermes real e instalada, exige uma leitura
pendente após conclusão prematura sem nova cobertura. Uma leitura real reabre
a decisão automática, preservando a rejeição fundamentada antes de ler todo o
escopo não relacionado exigido para aprovação. O modo automático também recebe
JSON apenas para sintaxe; chamadas de leitura continuam disponíveis. Alternar
categorias de erro não rearma uma falha já repetida na mesma cobertura.
Nada disso aumenta iterações, autoriza ferramentas ou escolhe a decisão.

### Interrupção mais recente: pagamento do provedor

O controle de continuação foi instalado e a nova revisão completou a inspeção
real. A sintaxe solicitada ao provedor não substituiu o parser: o primeiro
parecer foi rejeitado e recebeu feedback no mesmo turno. O HTTP 402 na chamada
seguinte interrompeu esse caminho antes de outra decisão. Não é uma nova falha
comprovada de leitura nem esgotamento de iterações; restavam 33 na tentativa
de conclusão preservada. Não há aprovação para recuperar do texto rejeitado.

Crédito disponível e teto de chamadas são controles diferentes. A rota específica
agora está implementada, qualificada com fixture e instalada, mas ainda não foi
executada contra o provedor real. Confirmação humana de remediação continua
pendente. O canário não consultou a chave real nem pagou ou alterou limites.

A retomada exige vincular o HTTP 402 original à execução, ao mesmo proxy,
contador e código; conferir crédito/chave por operações oficiais somente de
leitura; e registrar a condição modificada sob manutenção. O operador deve
confirmar a remediação explicitamente. A prova tem validade de 15 minutos e
não autoriza ativação, despacho ou aprovação. O registro exige tanto a
qualificação do worker de revisão quanto a do canário de pagamento, ambas
vinculadas à manutenção corrente e, no segundo caso, à imagem do controlador.

Confirmação perdida exige observar o efeito original, não reenviar a operação.
Uma conclusão parcial pode ser finalizada apenas a partir do recibo positivo
original, com identidade, contador e lock conferidos, sem repetir HTTP. A
execução seguinte terá leituras e parecer próprios; nenhum teste será congelado
por herdar evidências antigas. A rota não reinicia o autor nem encerra o incidente.
Não reaproveitar a recuperação de inspeção incompleta para essa falha.

Esse caminho ainda é uma operação assistida pelo operador. A classificação e o
escalonamento financeiro automáticos pela equipe não estão qualificados.

## Histórico recente: paginação e spill agregado

A versão anterior só projetava a fila depois de uma tentativa prematura de
resposta final. A versão instalada agora prepara fila, schema restrito e gate
de páginas desde a primeira chamada, inclusive no fluxo só de ferramentas.
Os testes novos recebem prioridade sem reduzir o escopo integral de aprovação.
Uma solicitação de mudanças fundamentada continua possível após a inspeção dos
testes novos e dos arquivos citados, sem forçar toda a leitura exigida para aprovar.

O ensaio anterior seguiu o caminho sem orientação e parou com 33 iterações ainda
disponíveis. O estado nativo `completed` significa que a execução terminou,
não que a revisão foi aprovada. O recibo do controlador registra
`native_terminal_verdict`, formato inválido para parecer e `automatic_retry=false`.
O diagnóstico estruturado não é uma falha funcional comprovada do produto.
A recuperação posterior mudou o perfil de código qualificado; não transformou
esse diagnóstico em aprovação nem herdou suas leituras para a revisão seguinte.

Na sucessora, a orientação inicial funcionou e o modelo usou lotes de leitura.
Entretanto, o gate admitia somente o lote recomendado daquele pedido, não todas
as páginas genuinamente pendentes. O modelo pediu páginas subsequentes de
arquivos já observados e um arquivo ainda não lido fora desse lote; recebeu
`operation_forbidden_in_test_review_v2` e interpretou o bloqueio de ordem como
perda de acesso. Seu escalonamento não satisfez o escopo de revisão integral.
O novo bloqueio permanece preservado, sem aprovação ou repetição automática.

A candidata seguinte separa recomendação de ordem de permissão: admite tuplas
de páginas ainda ausentes, inclusive offsets mistos de arquivos com tamanho já
observado. Arquivos desconhecidos só permitem a página inicial. Repetições,
EOF, caminhos estranhos e combinações inválidas continuam negados no handler.
Uma negativa de página passa a indicar ajuste de plano, não uma falha de ACL.
Essa correção foi qualificada e instalada; ainda falta o parecer nativo aceito.

O ensaio posterior expôs um limite distinto: embora `read_file` seja isento de
spill por resultado no Hermes, o orçamento agregado do turno ainda substituía
páginas completas por prévias em `/tmp`. Ler esses temporários não é permitido
pelo contrato, nem pode uma prévia contar como inspeção integral. O modelo
tentou recuperar páginas e encontrou deduplicação e negativas de plano.

A correção qualificada em `quality_review_budget.py` preserva os resultados
completos somente na fase autenticada de revisão imutável. Seu limite agregado
é o mesmo teto de 8 MiB do diário, não infinito. As 512 páginas/pares máximos,
os limites por leitura, a compactação real, o corpo de 2 MiB do proxy e as 40
iterações permanecem. Outros modos mantêm o orçamento original; não há nova
permissão para ler `/tmp`, executar terminal ou escrever.
Ela foi instalada sob manutenção com restauração verificada. A sucessora
comprovou o transporte integral dos 71 arquivos, mas ainda não produziu um
parecer aceito. A cadeia posterior permanece pendente.

A tentativa anterior, com 57/71 arquivos completos e 40 iterações consumidas,
permanece preservada como falha distinta. A rejeição histórica por corpo acima
de 512 KiB também não é a causa comprovada do bloqueio atual. Não se deve
reutilizar a prova de capacidade do proxy para autorizar uma repetição idêntica.

## Alcance da qualificação instalada

O canário Hermes/ACP passou com respostas locais fixas: continuação após uma
resposta prematura, handler restrito desde a primeira chamada, duplicata negada
e paradas por ausência de progresso e fim do orçamento. A extensão começou por
ferramentas, sem resposta prematura, e inspecionou 71 arquivos, 563.066 bytes e
219 páginas em sete chamadas principais e uma sumarização local. O maior lote
teve 274.113 caracteres, acima do limite agregado antigo de 200 mil, sem prévias
de spill. O controle legado continuou produzindo spill. Foram 157 leituras fora
da recomendação e quatro lotes mistos. Uma compactação real removeu 64 pares da
conversa sem perder cobertura no diário. Depois da leitura e compactação,
o guard recusou `request_changes` sem findings e devolveu a categoria específica;
o contrato da fase e os hashes permaneceram no pedido final sem ferramentas.
O controle de continuação também começou lendo os testes novos, emitiu a
promessa prematura e foi obrigado a executar a leitura pendente pelo handler.
O conjunto usou 16 respostas locais, sem chamadas ao provedor.

Essa prova cobre o caminho de ferramentas desde a primeira chamada com respostas
fixas. Não comprova a decisão de um modelo real, aprovação nativa, memória entre
reinícios ou memória compartilhada entre perfis. O controle de fronteira do
orçamento usa uma iteração sintética; a fábrica ACP mantém 40.

## Instalação de referência consultada

| Item | Estado observado em 24 de outubro |
|---|---|
| Controlador de qualidade | `delivery-kit-quality-v2-controller:20261023.36`, instalação concluída com execução desligada |
| Worker de autoria/revisão | Seletor `delivery-kit-quality-author-worker:20261023.11` |
| Correção instalada | Controles de revisão anteriores e registro restrito de recuperação por pagamento; sem remediação real comprovada |
| Instalação/ativação | Backup/restauração e preservação dos dados verificados; nova imagem ainda não ativada |
| Serviço host | Pin migrado para a nova imagem, fila/históricos preservados; desabilitado e descarregado |
| Manutenção na instalação | Selada e drenada após o encerramento com falha por pagamento |
| Revisão anterior terminal | Nativa `completed`, 71/71 arquivos completos; parecer inválido preservado, sem aprovação |
| Revisão intermediária terminal | 46/71 arquivos completos, duas respostas em prosa; sem aprovação |
| Última revisão após continuação por leitura real | 71/71 arquivos, 171 páginas; parecer inválido seguido de HTTP 402, execução nativa `failed` e equipe `technical_blocked` |
| Proxy na instalação | Parado após pausa persistente por pagamento; limite de corpo preservado em 2 MiB |
| Contador após a última tentativa | 6.291/10.000 chamadas; 3.709 restantes, sem reset; teto não é monetário |

Esta é uma fotografia, não monitoramento vivo: confirme tarefas, serviços e
leases antes de agir. Manutenção, pausa do provedor e proxy desligado são
controles distintos. A instalação verificou backup/restauração e preservou
dados, outros serviços e fila do scheduler. O teto de chamadas não é monetário.

## Próximos marcos, em ordem

1. Após confirmação humana de pagamento resolvido, obter prova real vinculada à falha e registrar a
   recuperação. Só então avaliar ativação separada; não repetir efeitos incertos.
2. Conferir parecer, independência e evidências no controlador; somente uma
   decisão válida pode avançar. Não herdar leituras ou ampliar iterações.
3. Exigir que a própria equipe conduza solicitações de mudanças, correção do
   autor e nova revisão dentro dos contratos persistentes.
4. Comprovar revisão e congelamento, Green, controles negativos, revisão da
   entrega, PR/CI e implantação/QA/rollback no mesmo commit sob o contrato v2.
5. Demonstrar diagnóstico e recuperação por Tech Lead/CTO, novo brief com cards
   dependentes e memória entre perfis, sem condução do operador.
6. Qualificar instalação limpa e reutilização por terceiros antes de apresentar
   a plataforma como pronta. A fatia inicial do Truco não encerrará sua v0.1.

O adaptador de recuperação de inspeção falha foi instalado e seu registro foi
exercitado antes da última revisão. Ele exige erro nativo preservado,
RPCs sem duplicação, leituras parciais válidas, lease fechada, worker retirado,
outro worker qualificado e manutenção selada. A causa do erro genérico permanece
explicitamente não comprovada. O registro não despacha modelo, não herda leituras
como aprovação e não encerra o incidente. Um parecer novo e independente continua
obrigatório. O registro e o despacho funcionaram; a tentativa anterior voltou
a bloquear, assim como a sucessora. Isso não comprova recuperação integral nem diagnóstico ou
replanejamento universalmente autônomos pelo CTO.

Uma política de revisão final e um executor fixo de revalidação existem em
fonte; ainda não constituem adaptador instalado ou despacho nativo. O executor
rodou a suíte completa da fixture novamente sob tarefa distinta, sem copiar
Green do autor nem fornecer terminal genérico. O canário Docker passou e o
auxiliar foi retirado; dois resultados anteriores de falha da fixture foram
preservados. Dez testes focados cobrem o executor e as verificações de rede.

O coordenador atual termina em `awaiting_independent_delivery_review`. Faltam
qualificação nativa, inspeção própria, decisão independente e continuidade até
PR/CI/deploy/QA/rollback. A política e o executor não conferem aprovação da entrega
ou permissão de publicação.

Os adaptadores de handoff/admissão e validação do controlador agora existem em
fonte, com feature gate desligado por padrão e sem instalação ou roteamento.
Conferem registros anteriores e identidades nativas, persistem o despacho antes
do efeito e ligam o recibo do job ao pedido e à tarefa exatos do revisor. Uma
confirmação perdida não reenvia o wakeup; capacidade e observação têm prazos
persistentes e proprietário técnico. Capabilities não são aprovação.
Intenções nativas ainda sem grant também reservam o perfil nessa fase; a
transição para `dispatch_intent` reconfere a reserva sob o lock transacional.

A revisão do código encontrou e reproduziu outro impedimento: a captura da
entrega contava execuções antigas do autor, mesmo quando a admissão já reconhecia
uma linhagem de correção legítima. O filtro agora é o mesmo, autenticado e
restrito; tarefas desconhecidas ou histórico divergente continuam recusados.
Os testes não foram removidos ou tornados permissivos. O adaptador de worker/
transporte final agora existe em fonte, exigindo o recibo original da suíte e
montando somente a candidata imutável. A fase `delivery_review_v2` tem handlers
de leitura paginada, sem escrita, shell ou capacidades legadas. Não foi instalada
ou ligada ao roteador. O parecer tipado e sua atestação agora existem em fonte:
exigem execução nativa concluída/fechada, inspeção do contêiner, sessão ACP e
leituras próprias de todos os arquivos no snapshot exato. Rejeição exige citação
real e aponta ao autor original; falhas técnicas ficam com o CTO. A atestação não
despacha correção ou libera merge. O adaptador seguinte agora prepara e registra
esse despacho em fonte, preservando o candidato rejeitado e o teste congelado.
Achados fora dos arquivos de produto vão ao CTO, sem permissão de editar testes.
Capacidade e confirmação perdida têm reservas/prazos, sem repetir POSTs.
O coordenador opt-in atravessa a revisão em fixtures: mudanças levam ao handoff
do autor e aprovação a `awaiting_publication`. Esses checkpoints seguem ativos,
com prazo de observação; não viram `HOMOLOGADA`. O comportamento antigo permanece
quando o flag dedicado está desligado.
Ainda faltam admissão/execução da correção, nova captura/validação/revisão e a
ponte de publicação. A imagem candidata `20261024.37` compilou e importou esses
módulos com execução desligada; não substituiu a instalação `20261023.36`.
São resultados de fixtures/build, não de agentes reais.

Outra regressão foi reproduzida e corrigida no diário: a fase final caía no
caminho legado, que descartava arquivos vazios e limitava a 128 páginas. Agora
tem o mesmo limite de 512 páginas autenticadas, sem importar recibos da fase de
revisão dos testes ou criar um parecer por declaração textual.

A consulta diagnóstica autorizada aos endpoints oficiais de créditos e chave
retornou HTTP 200 e disponibilidade em ambos. Não explicou o HTTP 402 anterior.
Nenhuma chamada ao modelo foi feita: hashes do contador e da pausa permaneceram
iguais, e o mesmo proxy foi desligado ao final. Não houve remediação ou retomada.

Uma execução intermediária da suíte falhou no probe de processo órfão. Um novo
teste reproduziu que a fixture contava reconciliação tardia de trabalho concluído
como nova execução. A correção ficou na fixture; SIGKILL, locks reais e execução
única continuam exigidos. A suíte completa foi reexecutada e passou. Isso não
constitui prova de recuperação de worker/modelo nem entrega do produto.

## Navegação

- [Arquitetura e fronteiras de autoridade](ARCHITECTURE.md)
- [Validação atual e evidências históricas](VALIDATION.md)
- [Critérios objetivos e trabalho restante](ROADMAP.md)
- [Instalação segura](SETUP.md)
- [Recuperação de QA e revisão](QA-PROTOCOL-RECOVERY.md)
- [Limites dos recibos de patch](PATCH-RECEIPTS.md)
