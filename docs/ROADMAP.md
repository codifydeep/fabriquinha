# Critérios para declarar autonomia

Não usamos quantidade de código, workers ativos ou percentual subjetivo como comprovação.

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
- Licença escolhida pelo proprietário, documentação de operação e testes de atualização/rollback.

Esses gates permanecem abertos até evidência específica. O ensaio atual não retoma automaticamente o Truco.

## Compatibilidade de transporte dos modelos

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
