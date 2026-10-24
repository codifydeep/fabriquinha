# Critérios para declarar autonomia

Não usamos quantidade de código, workers ativos ou percentual subjetivo como comprovação.

Uma [revisão estratégica com plano de simplificação](SIMPLIFICATION-REVIEW-2026-10-24.md)
foi aprovada em 24/10/2026. [S0/S1 passaram](HERMES-S1-QUALIFICATION.md) no escopo
sem modelo. A [fatia mecânica S2](HERMES-S2-QUALIFICATION.md) também passou;
S2 continua parcial e deve ser conectada à publicação/deploy em S3, sem outra
campanha de gates pré-Red. Nenhuma migração foi aplicada.
A [primeira integração S3](HERMES-S3-QUALIFICATION.md) passou com Git e suíte
integrada reais, mas PR/CI simulados. Próximo incremento: build/deploy/QA/rollback.
Os marcos abaixo inventariam o caminho anterior; não são instrução para continuar
ampliando a ponte v2 antes de implementar a estratégia aprovada.

## Prioridades atuais — 24 de outubro de 2026

Consulte [STATUS.md](STATUS.md) para a estimativa de prontidão e
[VALIDATION.md](VALIDATION.md) para a distinção entre provas atuais e históricas.
Os marcos abaixo permanecem abertos. Componentes já instalados são distinguidos
da qualificação ponta a ponta ainda necessária.

1. **Revisão com progresso verificável:** diário limitado de leituras reais,
   resistente à compactação do contexto; fila de páginas pendentes; bloqueio de
   repetição/EOF e diagnóstico estruturado antes de esgotar as 40 iterações.
   Progresso parcial conta; prosa, cache sem conteúdo e chamadas repetidas não.
   Diário, captura e paradas já estão instalados. O canário atual Hermes/ACP
   percorreu 563 KB, 219 páginas e uma compactação real. A fila dependia de uma
   resposta final prematura na versão anterior. A correção desde a primeira
   chamada também foi qualificada e instalada, sem impedir rejeição fundamentada.
   A revisão sucessora também bloqueou: o gate confundia o lote recomendado
   com todas as páginas pendentes permitidas. A candidata seguinte separa os
   dois conceitos e permite offsets mistos verificáveis, sem reduzir os gates.
   O marco continua aberto até parecer nativo aceito.
   O ensaio posterior chegou a 53/71 arquivos completos, mas produziu 33 prévias
   de spill e quatro deduplicações sem conteúdo. O transporte restrito à revisão foi
   qualificado acima do limiar antigo e instalado. A sucessora comprovou
   **71/71 arquivos**, mas o parecer foi rejeitado; leitura não equivale a aprovação.
2. **Qualificação antes de novo ensaio:** fixtures com múltiplos arquivos e
   páginas, controles negativos e Hermes/handlers/ACP reais sem provedor.
   O caminho só de ferramentas já passou pela prova física de escala e
   compactação e foi instalado sob manutenção, com recuperação específica.
   Corrigir o contrato apresentado da fase e o diagnóstico de saída inválida:
   `request_changes` requer achados concretos; Green e controles negativos não
   podem ser pré-condições da revisão dos testes que os antecede.
   Essa correção já passou no canário Hermes real após compactação e está
   instalada. A revisão seguinte parou com 46/71 arquivos e promessas em prosa.
   A continuação por leitura real já passou no novo canário; falta seu
   parecer nativo aceito. Não escolher a decisão em nome do revisor, reduzir evidências
   ou reutilizar prova de outro incidente.
3. **Contrato v2 ponta a ponta:** congelamento independente dos testes, Green,
   controles negativos, revisão da entrega, PR/CI, deploy, QA e rollback ligados
   ao mesmo commit. Não importar aprovações de contratos históricos.
4. **Recuperação pela equipe:** Tech Lead/CTO executam diagnóstico, SPIKE e
   replanejamento com evidências. Um impedimento apenas atribuído ao CTO não
   comprova recuperação; um limite de tentativas não cancela a release.
5. **Novo brief e reutilização:** cards dependentes e memória entre perfis sem
   direção do operador, seguidos de instalação limpa em outro ambiente.

O limite de requisição de 2 MiB já foi instalado e exercitado. A tentativa
anterior esgotou 40 iterações com 57/71 arquivos completos. Após a instalação do
diário e das paradas, a sucessora terminou bloqueada por falta de progresso,
com 16/71 completos e 33 iterações restantes. Nenhuma aprovou os testes.
Ampliar o corpo, trocar o modelo ou aumentar iterações não corrige a lacuna
identificada de orientação desde a primeira chamada. A correção dessa lacuna
está instalada, mas a revisão posterior expôs o bloqueio de ordem/permissão.
Essa segunda correção passou na prova física e foi instalada; todas as falhas permanecem.

### Critérios de saída da correção de orientação inicial

- A primeira chamada já contém a fila confiável; ferramenta e handler recusam
  páginas não planejadas, repetidas ou fora do arquivo desde esse ponto.
- Um fluxo só de ferramentas termina a inspeção com compactação real dentro
  do orçamento, sem fabricar recibos ou herdar leituras de outra execução.
- Uma rejeição fundamentada continua possível com o escopo exigido para
  `request_changes`; aprovação exige o escopo integral registrado.
- A nova revisão nativa produz parecer independente aceito pelo controlador.
  Parada estruturada, transporte válido ou mero estado `completed` não bastam.

Os três primeiros controles passaram offline; o caminho de leitura desde a
primeira resposta também passou no canário Hermes real com compactação.
Leituras fora da recomendação, offsets mistos e o orçamento agregado acima do
limiar antigo já foram exercitados na qualificação instalada. A revisão nativa
mais recente comprovou a inspeção integral. O último critério continua pendente:
obter decisão independente válida, sem dependências circulares entre fases.

### Correção instalada e critério do ensaio sucessor

- Apresentar a autoridade e o escopo da revisão dos testes a cada chamada,
  inclusive após compactação. Aprovação dos testes não é aprovação da entrega.
- Informar a causa específica da rejeição do parecer sem imprimir contexto
  privado nem tornar o validador permissivo. JSON válido pode ter decisão inválida.
- Exercitar rejeição sem findings, parecer obsoleto e inspeção incompleta,
  mantendo livres as decisões fundamentadas de aprovar, pedir mudanças ou escalar.
- Qualificar a mudança em ambiente isolado e instalar sob manutenção antes
  de registrar recuperação por condição modificada. Não repetir o mesmo perfil.

Os controles acima passaram na suíte offline e no canário físico. A correção
foi instalada; a revisão seguinte voltou a bloquear antes da decisão final.
O novo controle qualificado exige leitura pendente após resposta prematura e
reabre a decisão após progresso real, preservando rejeição fundamentada antecipada.
A aceitação de um novo parecer ainda não está comprovada; JSON válido ou leitura
completa não constituem esse critério.

A revisão após a continuação comprovou 71/71 arquivos. O primeiro parecer foi
rejeitado; o provedor respondeu HTTP 402 à continuação, que terminou como
falha nativa e bloqueio técnico. A recuperação específica já passou em fixture
Linux e foi instalada com execução desligada no controlador `20261023.36`.
O pin já foi migrado sem ativar o serviço. Antes de novo consumo, obter confirmação humana e
prova real de remediação, registrar a condição modificada e avaliar ativação
separada, mantendo contador, incidente e independência da próxima decisão.
Não usar a rota de inspeção incompleta para uma revisão que completou sua leitura.

### Critérios de saída da recuperação de pagamento

- Prova real recente de crédito/chave, vinculada ao evento 402 e à execução
  original, sem resetar contador ou elevar limites implicitamente.
- Qualificações de worker e pagamento na manutenção corrente; identidade do
  proxy e imagem do controlador revalidadas antes do registro.
- Efeito incerto observado pela mesma intenção, sem consultas ou registros
  duplicados. A fixture comprovou esse controle, não o percurso real inteiro.
- Nova revisão despachada pelo coordenador, com leituras e decisão próprias.
  Remediação de crédito não encerra o incidente nem equivale a aprovação.

Os controles determinísticos e o canário físico passaram; a consulta ao
provedor real e a retomada nativa não ocorreram. Automação do escalonamento
financeiro permanece trabalho futuro, sem atribuir compras ou credenciais aos agentes.

### Continuidade após Green

`quality_team_progress.py` ainda trata `awaiting_independent_delivery_review`
como checkpoint terminal de seu coordenador. Chegar a esse estado não é concluir
a release. A ponte seguinte precisa ser implementada e qualificada até revisão
independente da entrega, publicação por PR/CI e deploy/QA/rollback no mesmo SHA.
Não apresentar esse checkpoint como entrega autônoma completa.
Uma política de fatos da revisão final existe em fonte, com seis testes
sintéticos e sem instalação. O executor de revalidação da suíte foi acrescentado
e passou em canário Linux: mounts somente leitura, escrita negada e cinco pedidos
inválidos recusados, sem provedor. Dez testes focados cobrem executor e rede.
O handoff/admissão e o vínculo do job ao recibo do controlador foram implementados
em fonte e testados com registros nativos/SQLite de fixture. São opt-in, não
instalados nem conectados ao loop. Faltam os seguintes componentes e provas:

- Qualificação nativa do adaptador de worker/transporte final já existente em
  fonte, instalação e roteamento da admissão;
  a revisão dos testes não pode ser reutilizada como parecer da entrega.
- Qualificação nativa das leituras próprias, parser tipado e atestação
  independente já implementados em fonte, no snapshot/SHA exatos.
- Admissão e execução do handoff de correção já preparado/despachado em fonte;
  nova captura, Green, controles e revisão, preservando os testes congelados e
  invalidando a aprovação anterior para a nova entrega.
- Publicação após `awaiting_publication`, checkpoint ativo do coordenador em
  fonte, com PR/CI e deploy/QA/rollback no mesmo SHA.
- Qualificação nativa e recuperação de falhas sem o operador conduzir cada etapa.

A prova isolada do executor ou dos novos adaptadores não supre esses controles
nem autoriza publicação. A captura da entrega também foi corrigida em fonte
para reconhecer somente o histórico autenticado das revisões anteriores do
autor; uma tarefa desconhecida não passa a ser ignorada por estar concluída.

## Entrega

- Novo brief: refinamento, aprovação de negócio, arquitetura e decomposição pelos agentes.
- Cards dependentes: TDD, revisão independente, correção do autor e integração por PR.
- QA funcional e de regressão no commit implantado, com URL e recibos duráveis.
- Ciclo completo sem o operador editar artefatos, guiar handoffs ou dispensar controles.

## Resiliência

- Falha de worker, controlador e reinício do host sem duplicar entregas.
- Indisponibilidade do modelo, Telegram/interface ou GitHub visível e recuperável.
- Impedimento técnico escalado para Tech Lead/CTO; CEO somente para decisões de negócio, autoridade ou credenciais indispensáveis.
- Sem starvation silenciosa, looping de ação idêntica ou conclusão fictícia.
- Memória útil entre perfis e rodadas, preservando isolamento e proveniência.

## Reutilização

- Instalador único, configuração declarativa e remoção de dependências da máquina original.
- Imagens reproduzíveis e publicáveis, matriz de plataformas e política de atualizações.
- Novo repositório e nova instalação limpa sem copiar credenciais, sessões ou fixture identities.
- Preservar a licença MIT já escolhida, documentar operação e qualificar atualização/rollback.

Esses gates permanecem abertos até evidência específica. O ensaio atual não retoma automaticamente o Truco.

## Referência técnica e histórico dos adaptadores

As seções seguintes descrevem adaptações e fronteiras de etapas anteriores.
Menções a instalação pendente ou a ensaio futuro são históricas; não constituem
inventário vivo. A prioridade corrente é a revisão com progresso verificável,
descrita acima. Nenhum desses adaptadores, isoladamente, comprova autonomia.

### Compatibilidade de transporte dos modelos

O adaptador de Haiku preserva o contrato canônico validado localmente. Para
revisões tipadas, apenas o schema enviado ao provedor omite os combinadores
`anyOf` que o endpoint rejeita. SHA, campos obrigatórios, ferramentas permitidas
e limites permanecem vinculados; citações observadas e consistência entre
parecer e findings continuam obrigatórias no validador local. Uma resposta
inválida não constitui aprovação, mesmo que o provedor aceite o pedido.

`model_review_smoke.py` exercita esse transporte com uma fixture explicitamente
sintética, sem acesso a artefatos reais ou concessão de autoridade. Seu sucesso
não recupera automaticamente uma revisão bloqueada e não qualifica entrega.

Uma recuperação de revisão pode ser autorizada pelo controlador somente após
conferir a qualificação sintética no ledger e nos logs do proxy instalado, a
identidade do revisor, a lease encerrada, a leitura integral e o mesmo snapshot.
O histórico da falha fica preservado e o novo handoff tem identidade distinta.
Essa recuperação é única: outro erro não reinicia o contador nem libera o autor.
Seu parecer ainda precisa passar pelos controles normais e não homologa a release.

Conclusão de task e fechamento de lease são observações distintas. A validação
aguarda a finalização da mesma lease, com identidade e prazo persistentes, antes
de congelar arquivos. Um atraso de fechamento não é falha funcional, não autoriza
correção pelo autor e não constitui entrega. Incidentes históricos dessa corrida
só retornam à validação se a lease estiver fechada, não houver diagnósticos ativos
e nenhuma falha funcional tiver sido produzida; o histórico permanece preservado.

Diagnóstico de dependências usa apenas caminhos e hashes emitidos pelo validador
do snapshot. Leitura adicional não amplia o contrato de edição do autor. Uma
decisão concluída do CTO pode receber, uma única vez, o escopo instalado que
faltava no contexto; essa análise preserva o histórico e os limites de correção,
não reinicia o autor nem autoriza uma revisão do contrato. Replanejamento de
permissões e recuperação ponta a ponta ainda precisam de evidência própria.

`broker/product_scope_revision.py` define a política inicial de replanejamento
de edição de código Python: proposta vinculada ao contrato, snapshot e falha;
dependências observadas; revisão por perfil independente; testes congelados e
demais campos do contrato preservados. É uma política pura, não uma concessão
de ferramentas. `product_scope_contract.py` adiciona submissão tipada e leitura
obrigatória das dependências antes de propor ou revisar; `product_scope_ledger.py`
persiste intenção, proposta e qualificação, com identidade imutável, retomada
idempotente e autor ainda bloqueado após aprovação do plano.
`product_scope_execution.py` implementa o adaptador nativo: confere o responsável,
wakeup e tarefa concluída; autentica o patrocinador no estado persistente e nos
recibos do validador; verifica os bytes efetivamente lidos; reconcilia despachos
com confirmação perdida sem repetir intervenções. Resultados textuais ou falhas
terminais mantêm um impedimento visível, sem reiniciar o autor. Esses componentes
estão cobertos por testes offline, mas o adaptador ainda não está habilitado no
runtime. A seleção das montagens já está integrada ao código do broker:
confere tarefa, instrução, wakeup e snapshot exatos; é somente leitura e não
cria wakeups durante a construção do worker. Diagnósticos antigos não herdam
esse acesso e planos encerrados não reutilizam o snapshot como plano ativo.
`product_scope_materialize.py` materializa uma nova base, preservando o SHA Git
e todos os bytes da base original, exceto o contrato de edição revisado.
Reconfere o plano qualificado; vincula os hashes dos testes congelados sem
recriar Red; não aceita sobrescritas ou symlinks; grava arquivos por publicação
atômica e retoma cópias parciais exatas. O resultado não instala permissões.
`Dockerfile.scope-materializer` fornece a imagem dedicada, validada com uma
fixture descartável sem rede, credenciais ou socket Docker; essa fixture não
é uma revisão real dos agentes nem uma aprovação da entrega em andamento.
`product_scope_job.py` associa a materialização ao registro persistente:
reautentica as decisões nativas e leituras antes/depois do job, usa imagem fixa,
reconcilia o mesmo volume/job e guarda o recibo sem liberar o autor. Recibos
inválidos viram incidentes persistentes, sem execuções idênticas. Ainda falta
instalar os componentes e qualificar o despacho e a recuperação reais dos
agentes. `product_scope_base_verify.py` e sua imagem verificam a base revisada
novamente, com os dois volumes somente leitura. `product_scope_registration.py`
registra o resultado atomicamente em uma tabela própria; não muda a base global,
não aplica o contrato retroativamente nem emite ferramentas.
`product_scope_task_binding.py` adiciona um vínculo explícito e imutável com a
nova tarefa nativa do autor: exige despacho persistido e decisões reautenticadas,
recusa tarefas que já receberam grants ou contratos anteriores e não seleciona
automaticamente a revisão mais recente para outras tarefas. O vínculo não
desbloqueia o autor nem concede escrita. `product_scope_worker.py` integra a
seleção à base de seed, ao lockdown de arquivos e à lista de ferramentas ACP:
somente código recebe escrita, e o Red original deve continuar com os mesmos
hashes, comando, falha observada e revisão independente aprovada. O job de seed
confere os bytes dos testes congelados sem recriar o Red; tarefas antigas
continuam usando a base anterior. `product_scope_author.py` implementa um
despacho único, persistido antes do efeito nativo e reconciliado pelo mesmo
marcador. A admissão confere wakeup/tarefa, vincula a base antes dos grants e
confere o Red; falhas ficam bloqueadas com responsável e próxima ação. A nova
execução usa workspace por tarefa, sem reaproveitar o workspace da base antiga,
e recebe somente a instrução registrada em vez de diretivas históricas.
Esse adaptador ainda não está habilitado no loop instalado. A transição de TDD
agora referencia explicitamente o Red original através do novo workspace,
exige a suíte completa sem redução do número de testes e confere os hashes dos
testes preexistentes e congelados contra a base revisada. O recibo durável liga
as duas bases e o manifesto da entrega sem reescrever a evidência original nem
aprovar a entrega. `product_scope_delivery.py` confere a revisão independente
da entrega exata, as identidades nativas concluídas, o snapshot e a transição
de TDD. `portable_scope_gate.py` entrega ao publicador somente esse contrato
efetivo qualificado; ele é revalidado antes de merge e deploy. Não permite
compor revisões diferentes implicitamente nem dispensar CI, QA ou revisão.
Falta qualificar a coordenação completa do ciclo real e instalar os componentes
antes de habilitar o despacho e considerar o impedimento resolvido.

`product_scope_base_read.py` lê o contrato da base efetivamente registrada em
job fixo, sem rede, escrita, credenciais ou socket. `product_scope_bootstrap.py`
prepara o plano persistente a partir dessa leitura, do snapshot de falha e do
inventário do validador qualificado, com Red e revisão de testes preservados.
Não transforma a recomendação textual do CTO em permissão. O leitor também
foi executado sobre a base real do ensaio em volume somente leitura; isso
qualifica a leitura, não o fluxo autônomo completo. `product_scope_pipeline.py`
conecta os adaptadores ao loop com registro explícito por issue, seleção
persistente do impedimento e propriedade exclusiva até a admissão do autor.
O fluxo legado de handoffs e revisão de testes não disputa issues selecionadas.
Pausa e manutenção preservam essa propriedade; jobs pendentes e confirmações
incertas são observados novamente sem apagar suas intenções. Rejeições mantêm
incidente técnico visível, sem concluir entrega ou repetir a mesma ação.
Ainda falta instalar e qualificar essa coordenação no ciclo real dos agentes.
Os overlays `Dockerfile.broker-scope-pipeline-389` e
`Dockerfile.model-proxy-scope-111` preservam as imagens locais instaladas e
adicionam os componentes de escopo. São artefatos de qualificação desta
instalação, não um instalador portável: o operador deve conferir o ID da imagem
base indicado em cada arquivo antes do build. IDs locais de imagem não são
digests disponíveis em um registry. A troca dos serviços exige manutenção,
backup verificável e conferência das imagens efetivas antes de liberar agentes.
Os prompts de proposta/revisão de escopo também são isolados pelo controlador:
exigem a nota registrada e o wakeup/tarefa exatos, sem carregar protocolos
históricos conflitantes da descrição da issue e sem criar trabalho ao consultar.
Aprovar o plano não equivale a conceder escrita ou homologar.

`broker/native_scope_note.py` reconhece o envelope conhecido de wakeup
one-shot `time.due` para tarefas de escopo. Confere o identificador do wakeup,
o formato exato do rodapé e uma única ocorrência de seus campos; não procura
uma instrução confiável dentro de texto arbitrário. Após retirar somente os
metadados conhecidos, continuam obrigatórias a identidade nativa da tarefa,
o wakeup autenticado e a igualdade integral com a instrução registrada.
Falhas anteriores permanecem bloqueadas: instalar o decoder não reabre planos,
não dispensa revisão e não autoriza retentativas idênticas.
`product_scope_envelope_recovery.py` permite recuperação administrativa apenas
da falha pré-modelo comprovada: tarefa nativa falha, envelope verificado,
linhagem ACP anterior ao prompt, sponsor revalidado e apresentação corrigida
ensaiada em banco isolado. Cria outro plano com referência e prova da tentativa
anterior, que permanece inalterada. Não despacha agentes nem concede escrita;
o loop regular deve conduzir a nova proposta e sua revisão independente.
`scope_runtime_inventory.py` confere, em contêiner descartável sem rede,
os hashes de código dos adaptadores e de seus pontos de integração, incluindo
o resolver de mounts. A imagem do broker e a do proxy têm inventários distintos.
Essa verificação deve preceder a instalação dos overlays; importações isoladas
não provam que todos os módulos atualizados estão presentes na imagem.
Mesmo um inventário correto não qualifica mounts reais ou a entrega completa.
`product_scope_mount_recovery.py` reautentica a proposta concluída, confere
a política observada do worker falho e prova que o mount de evidência estava
ausente. O resolver corrigido é ensaiado com estado histórico isolado, sem
substituir globais do serviço, conceder capacidades ou recriar um worker.
O loop pode criar uma nova linhagem apenas de revisão quando essa qualificação
passa; mantém a tentativa falha e a proposta, e exige outro reviewer run real.
Uma intenção interrompida é retomada; qualificação rejeitada não é repetida
automaticamente. Esse caminho não recupera falhas funcionais ou aprovações.
Uma proposta reutilizada permanece ligada ao wakeup original por meio do hash
do plano pai imutável. A reautenticação não herda a revisão anterior: confere
as duas tarefas nativas, seus resultados e leituras completas. O loop também
pode retomar uma rejeição comprovadamente anterior à materialização quando
esse vínculo era a única pré-condição ausente, não existe job ou volume criado
e as decisões reautenticam. Preserva a rejeição no recibo da recuperação e
atualiza plano e coordenador em uma única transação. Jobs iniciados, intenções
mais completas, decisões alteradas ou qualificações rejeitadas não são resetados.
A inspeção de montagens trata apenas a omissão Docker de `ReadOnly: false`
como equivalente; fontes, destinos, flags true, ordem, tipos e outras opções
continuam exatos. Uma recuperação separada pode observar o mesmo job registrado
quando essa era a única diferença, o contêiner ainda está `created`, os prazos
originais não expiraram e todas as identidades reautenticam. Não recria o job,
não altera seu prazo nem repete a criação; jobs já iniciados não são elegíveis.
Uma aprovação de suíte, mesmo independente e verde, não qualifica publicação
da entrega com escopo revisado sem inspeção real. O gate requer recibos completos
de leitura do código autorizado e dos testes congelados, ligados à tarefa e
request do reviewer pelo transporte do controlador. Afirmações textuais ou
transcrições truncadas da interface não substituem essas leituras. Aprovações
anteriores sem inspeção permanecem históricas, mas não são prova suficiente
para liberar merge ou implantação; exigem revalidação independente.
`product_scope_review.py` deriva a lista de inspeção da base registrada e do
vínculo exato entre request, reviewer, autor e snapshot. O worker recebe essa
lista no contrato do handler: a suíte fixa é negada até que as páginas reais
estejam completas. O loop reabre uma única revisão do mesmo snapshot quando
detecta uma aprovação histórica sem inspeção, com marcador novo e evidência
anterior preservada. Não reinicia a implementação nem muda o Red. Uma segunda
revisão incompleta é um impedimento técnico visível, não outra retentativa.
O observador host também reconsulta esse gate para retomar uma sequência parada
pela falha funcional anterior. A retomada exige a entrega atual aprovada, tarefas
concluídas, inspeção completa, TDD congelado, base Git e contrato original exatos.
Ela preserva o incidente anterior no ledger e apenas reinicia a observação da
publicação: não autoriza nova execução do autor, merge, CI ou homologação. Esses
gates continuam sendo verificados pelo driver de entrega em cada transição.
A aprovação histórica e a revisão vigente não são selecionadas por timestamp.
Quando coexistem, o leitor exige o vínculo persistente de revalidação do mesmo
snapshot e qualifica novamente a inspeção, a independência e o TDD. Divergências
permanecem bloqueadas. Um handoff aprovado com seleção ambígua não fica em espera
infinita: gera impedimento técnico explícito, sem alterar as aprovações antigas.
`delivery_code_inspection.py` estende a inspeção obrigatória às entregas comuns
com TDD controlado. A lista vem das permissões persistentes do autor e dos testes
congelados, com identidades de tarefa, papel e snapshot conferidas. O handler
nega a suíte antes da leitura completa; o registro da aprovação reconfere os
recibos duráveis. Escopos revisados continuam sujeitos ao gate dedicado. Rotas
legadas não são convertidas retroativamente em entregas qualificadas.
