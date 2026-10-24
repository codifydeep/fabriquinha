# Instalação segura e limites

Estado de referência: **24 de outubro de 2026**. Leia [STATUS.md](STATUS.md)
antes de ativar agentes. O kit continua experimental; não há instalação completa
e autônoma qualificada para terceiros. Os passos abaixo não reproduzem por si
sós a instalação privada de referência.

## 1. Testes offline primeiro

Siga o README para criar um ambiente Python isolado e executar a suíte. Não são necessárias credenciais. Os checks públicos não executam os ensaios com modelos.

## 2. Plano de controle isolado

Docker Compose e acesso às imagens oficiais são necessários. Em `team-delivery-kit/`:

```bash
python evalctl.py init
python evalctl.py up
python evalctl.py verify
python evalctl.py status
```

Isso inicia somente PostgreSQL, backend e frontend do Multica, no grupo `delivery-kit-eval`. O frontend padrão é `http://localhost:19300` e a API `http://localhost:19080`. `init` gera `.local/evaluation.env` com permissões restritas; nunca o adicione ao Git.

Se essas portas ou o grupo já existirem, pare aqui: consulte a parametrização de `evalctl.py` antes de criar uma instalação distinta. Não sobreponha uma instalação existente.

```bash
python evalctl.py stop
```

`stop` preserva volumes. Não há motivo para usar `docker system prune`.

## 3. Agentes e execução

Não existe ainda um instalador genérico qualificado para toda a equipe. Antes de habilitar dispatch:

1. Escolha um repositório descartável, branch, contratos de testes e critérios de QA.
2. Gere imagens próprias a partir do código e confira a proveniência. Tags/digests locais de ensaios não são imagens públicas distribuídas.
3. Registre identidades, workspace e limites específicos da instalação.
4. Provisione a chave do modelo em armazenamento privado; não use automaticamente `provision_model_key.py`, que é um bridge específico do Hermes da instalação original.
5. Autorize conscientemente o socket Docker apenas para o controlador necessário.
6. Valide isolamento, revisão e recuperação antes de entregar trabalho de produto.

Não execute `compose.onboarding.yaml`, os overrides `port2` ou scripts de recuperação sem compreender seus efeitos. Alguns disparam chamadas cobradas, criam issues ou alteram GitHub. Relatórios e LaunchAgents da máquina original não são distribuídos; registro de serviços host exige configuração própria.

### Consulta e retomada de uma instalação existente

Na instalação de referência, a consulta abaixo não libera manutenção nem inicia
modelo. Execute a partir da raiz do repositório, com acesso autorizado ao Docker:

```bash
python team-delivery-kit/controller_maintenance_cli.py \
  --namespace delivery-kit-port2 --action status
```

O namespace é específico dessa instalação; não o copie para outra instância.
`sealed` com `drained=true` indica uma barreira de manutenção sem trabalho ativo,
não homologação. A disponibilidade da interface Multica também não prova que
o despacho ou o proxy do modelo estão ativos. Verifique-os separadamente, sem
imprimir configurações de ambiente ou credenciais.

Antes de retomar, confira imagens/hashes instalados, leases, efeitos Docker
pendentes e a condição que justificará qualquer recuperação. Uma falha antiga
não é corrigida apenas reiniciando serviços. Preserve o contador do proxy, os
limites aprovados e os recibos; não habilite fluxos legados junto do controlador
v2 exclusivo. Instalação de código ou edição de documentos não libera a barreira.

O perfil de referência mantém 40 iterações, dois workers simultâneos e no máximo
um por perfil. O limite instalado de corpo do proxy é 2 MiB, não um limite de
custo nem uma permissão para elevar o teto de chamadas. Não há fallback de
modelo automático. A qualificação específica deve anteceder um novo ensaio pago.

O modelo de referência é `anthropic/claude-haiku-5.5` via proxy OpenRouter.
O controlador `20261023.36` e o worker `20261023.11` já estão instalados nessa
referência; esses identificadores não constituem imagens publicadas para download.
O controlador novo está com execução desligada, manutenção selada/drenada e
serviço host desabilitado/descarregado. O pin foi migrado, com fila e histórico
preservados; a ativação da nova imagem continua pendente. Não use o pin antigo.
A sucessora liberada após a mudança qualificada também ficou bloqueada,
agora com 71/71 arquivos integralmente comprovados e parecer inválido. A
revisão dos testes não depende de Green ou dos controles negativos posteriores;
essa fronteira agora acompanha cada pedido ao modelo, mesmo após compactação.
O pedido final, após a inspeção exigida, usa JSON apenas para sintaxe e não
oferece ferramentas; a decisão ainda passa pelos gates locais. A nova revisão
despachada pelo coordenador terminou com 46/71 arquivos e promessas em prosa,
sem parecer aceito. A continuação por leitura real passou no canário seguinte
e foi instalada/ativada sob manutenção, com recuperação registrada. O
seletor atual inclui a correção de páginas pendentes e preserva resultados
completos em lotes grandes de revisão, sob o teto
de 8 MiB do diário. Isso não aumenta o corpo de 2 MiB do proxy nem permite ler
arquivos temporários de spill. Outros modos mantêm o orçamento original.
Isso não autoriza iniciar o Truco ou repetir indefinidamente o ensaio.

Manutenção, pausa do provedor e estado do contêiner do proxy são independentes.
Após a revisão terminal, a barreira foi selada/drenada e o proxy parado para
qualificação. A instalação verificou backup/restauração e migrou o pin sem
apagar histórico; a ativação separada manteve a barreira até conferir os
limites. Antes da nova revisão, o proxy foi reativado com 6.276/10.000 chamadas
e a manutenção liberada. A revisão terminou bloqueada em 6.282/10.000 e a
instância foi selada/drenada novamente, com proxy parado. Após qualificar e
instalar a continuação por leitura real, o proxy foi reativado e a barreira
liberada para novo despacho pelo coordenador. Não deduza liberação de dispatch a partir de contêineres
em execução, nem que selar manutenção pare o proxy.
Esse novo despacho terminou com 71/71 arquivos, parecer rejeitado e HTTP 402 na
continuação. A referência voltou à manutenção selada/drenada, com proxy parado
e pausa persistente por pagamento em 6.291/10.000 chamadas. Repor crédito não
dispensa conferir e qualificar a retomada; não zere o contador, troque o modelo
ou reutilize autorizações de uma classe diferente de falha.
Para conferir somente os serviços dessa instância:

```bash
docker ps -a \
  --filter name=delivery-kit-port2-execution-broker-1 \
  --filter name=delivery-kit-port2-model-proxy-1 \
  --format '{{.Names}} {{.State}} {{.Image}}'
```

Confirme a identidade exata antes de uma intervenção; filtros por nome não
autorizam parar ou remover os resultados. Não use `docker inspect` sem filtrar
campos: o ambiente completo pode conter segredos. O contador e o teto do proxy
devem persistir em trocas de imagem, reinícios e recuperações.

Parecer inválido com leitura completa é um incidente diferente de leitura
incompleta ou corpo de requisição excedido. Consulte o recibo e a rota de
recuperação compatível; não reclassifique o erro para reutilizar uma
autorização anterior. A edição desta documentação não autoriza nova execução.

### Recuperação específica após HTTP 402

Esta é uma operação assistida pelo operador, não parte da instalação genérica.
Os utilitários `quality_review_provider_access.py` e
`qualify_quality_provider_access.py` fazem parte do código de qualificação;
confira versão, proveniência e `--help` antes de usá-los em outra instalação.
A qualificação isolada já passou, mas não verificou o crédito real da chave.
Saldo informado e teto de chamadas não substituem a prova exigida pelo contrato.

Ordem operacional, sempre sobre identidades conferidas da instalação:

1. Manter a manutenção selada/drenada, sem workers ou efeitos pendentes.
   Conferir imagem instalada, backup/restauração e migração do pin do serviço.
2. Conferir duas qualificações na mesma manutenção: worker de revisão e
   canário Linux de pagamento na imagem atual do controlador. O canário usa
   fixture local, não credenciais reais.
3. Após confirmação humana de remediação, iniciar somente o proxy exato para
   consultar crédito/chave. A pausa persistente continua impedindo chamadas ao
   modelo. O CLI não inicia ou para serviços automaticamente.
4. Usar a ação `resolve` com namespace, imagem por digest, tarefa do autor,
   revisão que falhou e operação de manutenção exatos. O flag
   `--operator-confirms-remediation` registra confirmação efetivamente recebida,
   não uma autorização que o próprio agente possa presumir.
5. Preservar o recibo, parar o mesmo proxy e executar `register` com
   `--qualification` e `--payment-qualification` correspondentes. A prova expira
   em 15 minutos; contador, código e identidade não podem mudar nesse intervalo.
6. Conferir o registro antes de uma ativação separada. Registro não libera a
   manutenção, despacha agente, aprova testes ou autoriza merge. Só o coordenador
   poderá despachar a nova revisão depois da ativação controlada.

Se a confirmação de um efeito se perder, usar `observe-resolution` ou
`observe-registration` para a mesma operação, sem reenviar o efeito original.
`in_progress` ou `not_observed` não autorizam nova tentativa. A ação
`finish-resolution` só é admitida depois de observar `resolution_incomplete`,
com recibo positivo original ainda válido, contador inalterado e lock livre;
ela finaliza a operação sem repetir consultas HTTP. Falhas permanecem visíveis.

Nenhuma credencial ou resposta integral do provedor deve ir ao Git ou ao chat.
Os logs/recibos ficam em armazenamento privado restrito. Não use o resolver
legado diretamente para contornar o registro da recuperação v2. Não substitua
essa rota por recuperação de capacidade ou de inspeção incompleta.

### Executor experimental da revisão da entrega

`Dockerfile.quality-delivery-review-job` constrói um executor de operação fixa,
sem seleção de comandos ou testes pelo agente. Seu input é
`QUALITY_DELIVERY_REVIEW_JOB_JSON`, com plano e evidências completos, snapshot,
commit, perfil revisor e identidades distintas da autoria, revisão de testes e
implementação. O processo reexecuta a suíte; não aceita Green como substituto.

Os novos adaptadores `quality_delivery_review_handoff.py` e
`quality_delivery_review_validation.py`, em `broker/`, implementam em fonte a
admissão e o vínculo do recibo à execução. O flag `QUALITY_DELIVERY_REVIEW_ENABLED`
é desligado por padrão; ainda não existe configuração de ativação qualificada
para o fluxo completo. O adaptador `quality_delivery_review_launch.py` também
existe em fonte e exige o recibo original antes do worker somente leitura.
Não habilite o flag manualmente: faltam qualificação nativa, roteamento,
parecer e integração com o coordenador. O executor
isolado não faz essa autenticação nem aceita parecer. Na qualificação, a imagem
rodou como UID 10000, sem rede externa, credenciais, socket ou mounts graváveis
da entrega. Somente `/tmp` era gravável. Não habilite um workflow de produto
com base no resultado desse canário: a integração nativa ainda falta.

### Organização e retirada de testes

Use grupos Compose `delivery-kit-<instância>` para serviços,
`delivery-kit-<instância>-tests` para auxiliares e
`delivery-kit-<instância>-homologation` para candidatos implantados. Contêineres
criados pelo controlador devem usar `docker_grouping.py`.

Em cada fronteira de ciclo, inventarie recursos próprios e só retire os
obsoletos depois de confirmar leases ociosas e efeitos assentados. Para port2,
comece pela prévia de `cleanup_port2_history.py --tests-only`; depois revise
`cleanup_obsolete_images.py`. A aplicação da limpeza de imagens exige o hash do
plano conferido. Preserve logs privados, dados, snapshots, volumes, implantação
atual e versões de rollback. Nunca faça prune global nem altere `toso-*`,
`reforma` ou outros projetos como parte dessa rotina.

## Desktop Multica

O Desktop usa o endereço da **API**, não a porta do frontend. O arquivo `~/.multica/desktop.json` da versão avaliada suporta `schemaVersion`, `apiUrl`, `wsUrl` e `appUrl`. Consulte a documentação oficial da versão instalada antes de alterar; feche e reabra o app após mudanças.

Na instalação sem provedor de email, códigos temporários são registrados localmente. Não publique logs de autenticação. Na referência houve uma falha de atualização do stream de `docker logs`: não conclua que o pedido não chegou apenas por ausência nos logs; confira metadados no banco ou o retorno HTTP, sem expor segredos.

## Resposta humana de produto

Quando um planejamento estiver em `blocked_awaiting_ceo`, o operador pode registrar
a resposta realmente recebida do CEO, com as variáveis de instância corretas:

```bash
python planning_ceo_answer.py --run IDENTIDADE-DO-ENSAIO \
  --answer 'Resposta explícita do CEO à pergunta pendente' \
  --source 'Canal humano e data da decisão'
```

O registro é privado, imutável e ligado ao brief, configuração, commit-base,
issue, execução de Produto e hash das perguntas. Não inicia tarefas sozinho.
O supervisor registrado detecta o recibo e pede uma nova proposta a Produto,
preservando a pergunta anterior; CTO, Tech Lead e execução recebem a mesma
clarificação. Replay não duplica retomadas. Outra pergunta não é respondida
implicitamente. O registro não autoriza ferramentas, merge, exceções de testes
ou aprovação completa do brief. Workers não devem poder escrever nessa área.
