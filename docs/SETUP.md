# Instalação segura e limites

Estado de referência: **23 de outubro de 2026**. Leia [STATUS.md](STATUS.md)
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
O controlador `20261023.32` e o worker `20261023.8` já estão instalados nessa
referência; esses identificadores não constituem imagens publicadas para download.
A sucessora liberada após a mudança qualificada também ficou bloqueada.
O seletor atual inclui a correção de páginas pendentes, ainda sem aprovação nativa.
Isso não autoriza iniciar o Truco ou repetir indefinidamente o ensaio.

Manutenção, pausa do provedor e estado do contêiner do proxy são independentes.
Após a revisão terminal de 23 de outubro, a barreira foi selada/drenada e o
proxy parado novamente, preservando contador e teto. Para conferir somente
os serviços dessa instância:

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
