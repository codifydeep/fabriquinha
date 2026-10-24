# Status do projeto — 23 de outubro de 2026

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
As estimativas foram mantidas nesta atualização: o avanço para 71/71 leituras
não comprova decisão válida nem autonomia ponta a ponta.

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
  host foi migrado para o novo pin, sem resetar sua fila ou seu histórico.
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
- A última suíte offline registrada com captura, enforcement e paradas executou
  **4.384 testes: 4.376 aprovados e oito skips preexistentes**, sem falhas.
  Os 44 testes focados desta correção também passaram. Essas provas offline
  não substituem a qualificação nativa.

Não houve congelamento dos testes, Green ou homologação nessa linhagem v2.

## Bloqueio atual: decisão da fase de revisão dos testes

A revisão mais recente completou a inspeção integral. Antes de parar, o worker
produziu três tentativas com prosa fora do contrato e uma tentativa JSON com
`action=request_changes`, hashes correspondentes e `findings=[]`. O contrato
exige achados concretos para solicitar mudanças; um objeto JSON bem formado
não basta. O resultado terminal foi um diagnóstico, não um parecer aceito.

A justificativa dessa última tentativa condicionava a aprovação dos testes a
Green, controles negativos e uma aprovação adicional do CTO. Isso inverte o
contrato vigente: os testes são revisados e congelados **antes** da implementação
e de Green. Aprovar os testes não aprova implementação, merge ou release.
Decisões técnicas continuam com a equipe, sem repassar essa questão ao CEO.

A correção ainda necessária é explicitar essa fronteira em cada chamada,
inclusive após compactação, e devolver erros de contrato específicos sem
afrouxar o validador. Saída tipada pode auxiliar o formato, mas não resolve
sozinha a dependência circular. Outra execução exige mudança qualificada;
não se deve extrair aprovação da prosa, inventar findings ou repetir o mesmo
perfil. Essa correção ainda não está instalada nem qualificada nativamente.

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
219 páginas em seis chamadas principais e uma sumarização local. O maior lote
teve 274.113 caracteres, acima do limite agregado antigo de 200 mil, sem prévias
de spill. O controle legado continuou produzindo spill. Foram 157 leituras fora
da recomendação e quatro lotes mistos. Uma compactação real removeu 64 pares da
conversa sem perder cobertura no diário. O conjunto usou 14 respostas locais,
sem chamadas ao provedor.

Essa prova cobre o caminho de ferramentas desde a primeira chamada com respostas
fixas. Não comprova a decisão de um modelo real, aprovação nativa, memória entre
reinícios ou memória compartilhada entre perfis. O controle de fronteira do
orçamento usa uma iteração sintética; a fábrica ACP mantém 40.

## Instalação de referência consultada

| Item | Estado observado em 23 de outubro |
|---|---|
| Controlador de qualidade | `delivery-kit-quality-v2-controller:20261023.33`, instalado para qualificação controlada |
| Worker de autoria/revisão | Seletor `delivery-kit-quality-author-worker:20261023.9` |
| Correção mais recente | Preservação limitada dos resultados completos antes da compactação, qualificada e instalada |
| Manutenção na instalação | `sealed`, `drained=true`, consultada novamente nesta atualização |
| Última revisão terminal | Nativa `completed`, 71/71 arquivos completos; parecer inválido e controlador `technical_blocked` |
| Proxy na instalação | Contêiner em execução; limite de corpo configurado em 2 MiB. Isso não implica despacho ativo |
| Contador consultado | 6.276/10.000 chamadas; 3.724 restantes, sem reset; teto não é monetário |

Esta é uma fotografia, não monitoramento vivo: confirme tarefas, serviços e
leases antes de agir. Manutenção, pausa do provedor e proxy desligado são
controles distintos. A instalação verificou backup/restauração e preservou
dados, outros serviços e fila do scheduler. O teto de chamadas não é monetário.

## Próximos marcos, em ordem

1. Corrigir a apresentação persistente do contrato da fase: aprovação dos
   testes antecede Green; solicitação de mudanças requer achado concreto.
2. Qualificar diagnóstico e formato de saída, inclusive após compactação,
   instalar sob manutenção e obter novo parecer independente válido. Não
   repetir o perfil anterior, herdar leituras ou ampliar iterações.
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

Uma política local de revisão final da entrega está em elaboração, mas não
constitui adaptador instalado ou despacho nativo. O coordenador atual termina
em `awaiting_independent_delivery_review`; faltam autenticação das evidências
reais, validação própria do revisor e continuidade até PR/CI/deploy/QA/rollback.
Não houve nova execução da suíte completa nesta atualização documental; o total
de 4.384 acima refere-se à última execução registrada para o código instalado.

## Navegação

- [Arquitetura e fronteiras de autoridade](ARCHITECTURE.md)
- [Validação atual e evidências históricas](VALIDATION.md)
- [Critérios objetivos e trabalho restante](ROADMAP.md)
- [Instalação segura](SETUP.md)
- [Recuperação de QA e revisão](QA-PROTOCOL-RECOVERY.md)
- [Limites dos recibos de patch](PATCH-RECEIPTS.md)
