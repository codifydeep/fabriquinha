# Instalação segura e limites

Estado de referência revisto: **27 de outubro de 2026**. Leia [STATUS.md](STATUS.md)
antes de ativar agentes. O kit continua experimental; não há instalação completa
e autônoma qualificada para terceiros. Os passos abaixo não reproduzem por si
sós a instalação privada de referência.

Para o caminho novo Hermes aprovado, consulte as provas isoladas
[S1](HERMES-S1-QUALIFICATION.md), [S2](HERMES-S2-QUALIFICATION.md) e
[S3](HERMES-S3-QUALIFICATION.md).
Elas não exigem Multica nem iniciam a instalação antiga. Os comandos Multica
abaixo documentam a referência histórica; não são pré-requisito da simplificação.
S3 pode construir e manter um demo local com Compose, QA de navegador e rollback,
sem modelo ou GitHub real. S6 acrescenta uma receita pública do navegador,
qualificada em Linux ARM64; a instalação e o ciclo real completos ainda precisam
da qualificação de portabilidade. Imagens continuam selecionadas por ID exato.
O [serviço contínuo TDD](HERMES-RUNTIME-QUALIFICATION.md) já passou em isolamento
com reinício/crash/retomada. Sua CLI oferece consulta do board sem modelo;
as rotas de fixture expiram e não devem ser reutilizadas como produção. Provedores
reais exigem política privada explicitamente habilitada e limite de consumo.
Instalações históricas não são entradas de reprodução. A recuperação do PR 57
chegou à homologação assistida. O PR 58 também foi homologado após correção
externa da CI. O [S4 seguinte](HERMES-S4-QUALIFICATION.md), PR 59, completou o ciclo
técnico sem intervenção externa; isso ainda não qualifica o instalador para terceiros.
Consulte o status atual antes de ativar
serviços e não reutilize sessões ou evidências históricas para fabricar uma nova
qualificação. A auditoria sozinha não autoriza ativação.
O [diagnóstico técnico](HERMES-RECOVERY-QUALIFICATION.md) acrescenta configuração
explícita de Lead/CTO e cards nativos de recuperação com SPIKE. Sua prova também
usa respostas locais; não constitui ativação dos nove perfis em produção.
A [outbox/observabilidade](HERMES-NOTIFICATIONS-QUALIFICATION.md) também foi
qualificada com transporte local. `notifications.json` pertence à raiz privada
da instalação, nunca ao Git; não copie tokens para SOULs, cards ou testes. O modo
de qualificação recusa Telegram real. A futura ativação depende do destino
explicitamente configurado, sem reativar os gateways antigos por consequência.

## Caminho atual e referência histórica

O caminho novo é `src/fabriquinha`, com preparação parcial por
`scripts/prepare_hermes_project.py`. Esse script não instala imagens, provisiona
GitHub ou inicia relay/serviço. A [revisão atual](EXECUTION-REVIEW-2026-10-26.md)
documenta os achados, as mudanças propostas e as lacunas de S6; não autoriza retomada.
A CLI de preparação exige `--max-output-tokens` explícito: 2048, 4096, 8192 ou 16384,
conforme política autorizada. O valor é preservado no preparo e consumido pelo
relay/SDK; escolhê-lo não habilita o provedor nem aumenta o teto de chamadas.
O suporte a 16384 foi autorizado e usado no ensaio real. A política de referência
tem saída máxima 16384 e teto específico de 7.000 chamadas; sua ativação segue a
pausa/retomada explícita do proprietário, consultável no status local. Esses
valores privados não são uma autorização de consumo para novas
instalações. Limite de chamadas e saída por resposta são controles distintos.

Para consultar uma instalação existente, use o Python do SDK já provisionado,
com `PYTHONPATH=src`, e `python -m fabriquinha.runtime status --root
<raiz-privada> --upstream <checkout-Hermes-fixado>`. A consulta não retoma
dispatch. Os caminhos são inputs privados do operador; não copie instalações
ou credenciais de outra máquina.

### Validação fixada e consulta de consumo

A preparação de uma instalação nova grava `validation_bundle` e `control_contract`
em `installation.json`, usando scripts capturados em snapshot imutável. As novas
instalações reais também fixam `profile_contract`. Não edite esses campos para
promover uma instalação legada ou reaproveitar suas aprovações.
Trabalho real exige esse pin; instalações antigas permanecem consultáveis como
história. Migração geral de upgrades ainda depende de S6.

Com o relay local já iniciado pelo operador, use a mesma CLI de status trocando
`status` por `costs`. A consulta funciona com política de inferência desabilitada;
não inicia o serviço, faz chamadas ao modelo nem arquiva pausas financeiras.
Custos ausentes não são zero, e contadores históricos sem atribuição continuam
visíveis. Veja os campos e os limites no [ADR 0005](ADR-0005-VALIDATION-AND-ACCOUNTING.md).

### Compatibilidade da atribuição por atividade

O SDK atual gera internamente `/activities/<hash>/v1` para cada execução. Mantenha
a rota configurada pelo operador em `/v1`; não copie um hash para a configuração.
O relay deve anunciar `activity_scopes: path-v1`. Sem essa capacidade, o preflight
recusa despacho pago com `activity_routing_unavailable`. Atualize SDK/controlador
e relay em uma manutenção coordenada, preservando contador, pausas financeiras,
credenciais e dados. Não aponte código novo para um relay histórico só porque ele
responde a `/status`.

A prova isolada pode ser executada com o Python do SDK e um diretório privado novo:

```sh
<python-do-SDK> scripts/qualify_auxiliary_attribution.py \
  --root <raiz-privada-nova> --upstream <checkout-Hermes-fixado>
```

O script usa o compressor real com provedor simulado e apenas sua porta local.
Não usa a chave ou o contador de produção e não qualifica uma entrega de produto.
Veja os limites no [ADR 0005](ADR-0005-VALIDATION-AND-ACCOUNTING.md).

### Perfis gerenciados e modelo do controlador

`prepare_hermes_project.py` prepara uma raiz privada **nova**, vazia e pausada,
com perfis nomeados, a rota local e política de inferência desabilitada. O SDK,
upstream fixado e imagens devem existir; o script não inicia relay, gateway ou
workers, não provisiona chaves e não altera GitHub. Exemplo de entrada:

```sh
<python-do-SDK> scripts/prepare_hermes_project.py \
  --root <raiz-privada-nova> --upstream <checkout-Hermes-fixado> \
  --project <project.json-revisado> --model <modelo-autorizado> \
  --provider-port <porta-local-livre> --max-calls <teto-autorizado> \
  --max-output-tokens <limite-autorizado>
```

Nesta fronteira, **modelo e orçamento pertencem a `provider-policy.json` e
`route.json` privados**, sob controle do operador. Os perfis SDK gerados não
escolhem outro modelo ou provedor. Não configure seus modelos pelo menu do
Hermes esperando alterar a rota da equipe: a divergência será recusada. Trocar
o modelo exige manutenção coordenada e nova validação, preservando o contador.
O arquivo `config.yaml` gerenciado usa JSON compatível com YAML, produzido por
`fabriquinha.profile_policy.configuration()`; a comparação é pelo conteúdo
canônico, não pela ordem ou espaços. Alterações manuais e YAML fora desse
formato não são uma configuração suportada do perfil gerenciado.

`doctor` e `status` mostram erros por perfil e seu responsável técnico. Um perfil
divergente é recusado no spawn; os demais continuam elegíveis. O worker confere
novamente antes do sandbox/SDK e durante a atividade. A recusa usa a espera de
infraestrutura existente, preservando fase/sessão e sem gastar o limite de falhas
funcionais. O cooldown nativo continua em vigor; readiness não significa que um
worker já foi executado ou que uma tarefa foi concluída.

O preflight confere a configuração atual e os defaults/normalização efetivos do
SDK. Um arquivo ilegível ou corrompido **não** é qualificado usando o backup
last-known-good. O carregador Hermes pode criar seu backup nativo limitado; o
preflight não reescreve a configuração. Também recusa rotas auxiliares explícitas,
fallbacks, hooks/extensões não qualificados, memória externa e credenciais nos
homes SDK. Políticas gerenciadas pelo administrador exigem sua própria
qualificação; o kit não as ignora para passar o teste. Credenciais de modelo e
canal ficam no controlador/relay, fora desses homes.

### Identidade GitHub explícita

O Hermes fixado isola a identidade GitHub de cada perfil nomeado. Um `gh api
user` bem-sucedido no shell do operador não comprova que o perfil responsável
pela integração consegue autenticar. O `doctor` exige também o vínculo abaixo
em projetos reais com CI local; isso verifica configuração, não disponibilidade
atual da API nem autorização de merge.

Autentique primeiro a conta declarada como `local_ci.publisher` em um diretório
GitHub CLI administrado pelo controlador. Depois, com a instalação pausada e
drenada, execute usando o SDK e a fonte revisados:

```sh
PYTHONPATH=<fonte-revisada>/src <python-do-SDK> -m fabriquinha.github_auth \
  --root <raiz-privada> --upstream <checkout-Hermes-fixado> \
  --config-dir <diretorio-absoluto-gh-do-controlador>
```

Esse comando faz apenas uma consulta de conta na API e provisiona
`github-auth.json` privado e as referências não secretas `GH_CONFIG_DIR`/`GH_HOST`
nos perfis de integração e seus revisores. O SDK nativo continua usando essas
identidades na conclusão do Kanban. Não são copiados tokens, `hosts.yml` ou
sessões. O diretório deve ficar fora da instalação e nunca é montado em
contêineres de execução, revisão ou testes. A mesma conta pode servir aos perfis;
a independência de revisão continua sendo a do papel/execução/SHA, não identidades
GitHub fictícias. Perfis no host não são uma barreira contra o administrador.

Conta divergente, `.env` com credenciais ou configuração desconhecida impedem o
provisionamento antes da escrita. Uma interrupção parcial mantém o `doctor`
recusando prontidão; a repetição com a mesma identidade termina o vínculo. Trocar
uma identidade já vinculada exige migração explícita. Nunca resolva a recusa
retirando o perfil das operações GitHub para fazê-las herdar o login ambiente.

Os handlers continuam impondo as permissões da fase, incluindo revisão imutável;
o preflight não substitui essa barreira nem é uma sandbox contra o administrador
capaz de modificar arquivos. Mudanças operacionais devem ocorrer sob pausa
drenada. Instalações históricas sem `profile_contract` permanecem consultáveis,
mas o código novo recusa trabalho real até uma migração qualificada. Adicionar
o campo manualmente não constitui essa migração.

```sh
<python-do-SDK> scripts/qualify_profile_admission.py \
  --root <privado>/perfis-novos --upstream <checkout-Hermes-fixado> \
  --image <ID-validation> --browser-image <ID-qa>
<python-do-SDK> scripts/qualify_hermes_operations.py \
  --root <privado>/operacao-nova --upstream <checkout-Hermes-fixado> \
  --image <ID-validation> --managed-profiles
```

A primeira prova prepara nove perfis e usa um callback sem worker para verificar
admissão independente no Kanban. A segunda executa SDK/sandboxes reais, TDD,
pausa, reinício e retomada com respostas HTTP locais. Nenhuma faz chamada paga,
altera GitHub ou qualifica uma nova entrega de produto.

### Imagens públicas da stack Python/HTTP

Faça o build a partir do clone Git revisado, antes de exportar a fonte operacional.
`Dockerfile.validation-browser` agora oferece dois alvos a partir do mesmo
toolchain público: `validation` (UID 65534 e suíte fixa) e `qa` (UID 10000 e
entrada Python). Escolha tags próprias da instância; as abaixo são exemplos.

```sh
docker build --target validation -f Dockerfile.validation-browser \
  -t delivery-kit-example-validation:20261027.1 .
docker build --target qa -f Dockerfile.validation-browser \
  -t delivery-kit-example-browser:20261027.1 .
docker image inspect --format '{{.Id}}' delivery-kit-example-validation:20261027.1
docker image inspect --format '{{.Id}}' delivery-kit-example-browser:20261027.1
```

Use os IDs retornados, respectivamente, em `validation_image` e `browser_image`
do seu `project.json`. Não copie IDs da máquina de referência. A base Python está
fixada por digest público; o pacote Playwright e suas dependências têm versões e
hashes em `scripts/requirements-browser.txt`. O instalador oficial baixa somente
Chromium headless e suas bibliotecas de sistema, conforme os procedimentos de
[Docker](https://playwright.dev/python/docs/docker) e
[headless shell](https://playwright.dev/python/docs/browsers#chromium-headless-shell).
O build inicial requer internet; os testes continuam sem rede externa, chave,
socket Docker ou instalações de pacotes em tempo de execução.

O contexto Docker é limitado pelo `.dockerignore` específico da receita. O build
não usa imagens de Reforma/Toso nem suas credenciais. Base e wheels fixados não
tornam o build bit a bit determinístico: as bibliotecas do sistema vêm dos
repositórios Debian vigentes. Registre o ID resultante e qualifique-o antes de
usar em uma instalação; não troque o ID de um projeto ativo silenciosamente.

As provas públicas usam raízes privadas novas e não iniciam os agentes:

```sh
python3.14 -B scripts/qualify_browser_tdd.py \
  --root <privado>/browser-tdd --image <ID-validation>
python3.14 -B scripts/qualify_browser_image.py \
  --root <privado>/browser-qa --image <ID-qa>
```

Na referência ARM64, quatro jobs comprovaram Red, Green, controle comportamental,
teste auxiliar preservado e isolamento. Outro job executou o driver QA real no
UID 10000 contra um servidor de fixture dentro do próprio contêiner, com raiz
somente leitura e rede `none`. Todos os contêineres foram retirados. Essa última
prova qualifica o toolchain; não é QA de um produto implantado nem homologação.
Outras arquiteturas e o novo ciclo completo de S6 continuam pendentes.

### Redes explícitas e prévia do bootstrap

Escolha `network_pool` **antes** do preparo da raiz privada. O exemplo contém
`10.245.248.0/26`; confira Docker, LAN e VPN e substitua-o se necessário. O pool
deve ser IPv4 RFC1918 alinhado em `/26`. Os três primeiros `/28` destinam-se,
respectivamente, à homologação, QA interno e serviços centrais; o último fica
reservado. A verificação automática cobre conflitos no Docker, não rotas da LAN
ou VPN. Não copie o pool de outra instância na mesma máquina.

```sh
<python-do-SDK> scripts/prepare_hermes_networks.py \
  --root <raiz-privada> --upstream <checkout-Hermes-fixado>
```

O comando exige pausa e workers/claims/sandboxes encerrados. Grava as intenções
no journal existente e cria somente as duas redes de homologação, com owner e
sub-redes exatos. Confirmação perdida é observada sem outro `create`; reexecução
confere os IDs, labels e IPAM reais. Um conflito não causa limpeza de outras
redes. A CLI preserva o caminho sem pool de instalações antigas; seu fingerprint
não muda por causa da adição deste campo opcional.

`deployment-network-preflight.json` informa o `core_subnet`. O Compose público do
relay exige `FABRIQUINHA_CORE_SUBNET` com esse valor e `FABRIQUINHA_PROJECT` com o
fingerprint da instalação, além dos inputs já declarados no próprio arquivo.
Iniciar o Compose do relay é outra operação; reservar redes não o inicia nem
autoriza inferência. O preparo real de redes e a renderização dessa configuração
passaram em isolamento; o relay/canal/entrega da instalação portátil ainda precisam
da qualificação completa de S6.

Antes de criar a branch de produto, gere a proposta local:

```sh
<python-do-SDK> scripts/bootstrap_hermes_branch.py \
  --root <raiz-privada> --upstream <checkout-Hermes-fixado> --preview
```

A prévia guarda o diff privado em `private/bootstrap/preview.json` e retorna SHA,
parent e caminhos adicionados/modificados/removidos. Não faz push nem altera
proteções. Se a semente substituir arquivos existentes, obtenha o aceite do dono
para o escopo/reset de baseline — especialmente testes — antes de aplicar com
`--expect-head <SHA-da-previa-aprovada>`. O aceite desse SHA é persistido para a
retomada da mesma operação; não vale para outra proposta. Uma mudança de main ou
de sua proteção após o preparo recusa a mutação antes do push. O comando trabalha
somente na branch nova e nunca é uma entrega de produto ou dispensa dos gates.

### Revisão de execução isolada do checkout

#### Medidor novo e preservação do histórico

O relay não cria nem repara contadores. Para uma instalação realmente nova,
prepare um diretório privado vazio pertencente ao usuário que executará o relay:

```sh
mkdir -m 700 <privado>/meter
python3 scripts/initialize_provider_meter.py --new-meter <privado>/meter
```

O comando cria `calls.json` com zero e um marcador de origem, sem chamada à
OpenRouter, chave, habilitação ou alteração de teto. Recusa links, diretório
público, qualquer conteúdo anterior e inicialização interrompida. **Não use em
uma instalação existente**, nem apague seu medidor para conseguir executá-lo.
Um contador ausente em instalação antiga é recuperação de dados, não bootstrap.

O Compose de referência recebe volumes externos de medidor e credencial. Para
uma instalação **nova**, escolha nomes exclusivos em `FABRIQUINHA_METER_VOLUME`
e `FABRIQUINHA_SECRET_VOLUME`. Confira que não existem em `docker volume ls`;
não reutilize volumes históricos. Com os demais parâmetros do Compose definidos
em um arquivo privado `provider-compose.env`, crie somente esses dois volumes:

```sh
docker volume create --label "com.docker.compose.project=$FABRIQUINHA_INSTANCE" "$FABRIQUINHA_METER_VOLUME"
docker volume create --label "com.docker.compose.project=$FABRIQUINHA_INSTANCE" "$FABRIQUINHA_SECRET_VOLUME"
docker compose --env-file <privado>/provider-compose.env \
  -f examples/python-http/compose.provider.yml --profile bootstrap \
  run --rm -T --no-deps storage-bootstrap < <arquivo-privado-da-chave>
```

O arquivo de chave deve ser privado (0600), nunca parâmetro, variável de ambiente
com o valor da chave ou conteúdo Git. O helper lê stdin sem imprimir a chave;
executa como root apenas para definir UID/GID 10000 e permissões, sem rede,
socket ou ferramentas de agente. Refusa qualquer conteúdo preexistente em ambos
os volumes, inclusive estado parcial. Não o repita para reparar uma instalação.
O relay recebe a credencial somente para leitura e continua desabilitado pela
política inicial. A inicialização não autoriza inferência.

`scripts/qualify_provider_storage.py` reproduz o bootstrap com chave fictícia,
recusa de sobrescrita e leitura pelo UID do relay. Retém dois volumes mínimos
de prova; os helpers agrupados são retirados por `--rm`.

#### Fonte fixada

Para uma fronteira de qualificação, exporte uma revisão Git publicada e já
testada para um diretório privado novo. O comando lê objetos do commit, não
arquivos alterados ou não rastreados do checkout. Não faz fetch nem comprova que
o commit foi publicado: confirme isso antes. Manter a estrutura relativa é
necessário para os mounts, o agrupamento Docker e a receita de build.

```bash
fabriquinha_revision=$(git rev-parse HEAD)
PYTHONPATH=src python3.14 -B -m fabriquinha.source freeze \
  --checkout "$PWD" --revision "$fabriquinha_revision" \
  --destination <privado>/runtime-source
```

O destino **não deve existir**. O resultado contém commit, quantidade de arquivos
e `source_digest`; guarde esse hash fora da cópia, em estado privado. O export
contém apenas os caminhos públicos necessários ao runtime e preparo: não copia
homes, credenciais, bancos, sessões, histórico operacional nem worktrees. Um
export interrompido permanece visível e não é sobrescrito automaticamente.
Os arquivos ficam sem permissão de escrita; isso protege de alterações acidentais,
não do proprietário capaz de mudar permissões.

Verifique a cópia usando o hash registrado, não um hash recalculado após uma
alteração. Arquivos extras, ausentes, modificados, links e escrita habilitada
recusam a verificação:

```sh
PYTHONPATH=src python3.14 -B -m fabriquinha.source verify \
  --source <privado>/runtime-source --expect-source <source_digest>
```

O Python do SDK e o checkout upstream continuam explicitamente fixados. Use a
entrada abaixo para `status`, `doctor`, `costs`, `pause`, `resume` ou `serve`.
Ela substitui o processo pelo runtime existente, com `PYTHONPATH` da cópia
verificada e sem importação implícita do diretório de trabalho ou pacotes do
usuário. A mesma identificação da fonte é herdada pelos workers.

```sh
python3.14 -B scripts/run_hermes_runtime.py status \
  --source <privado>/runtime-source --expect-source <source_digest> \
  --python <python-do-SDK> --root <raiz-privada-da-instancia> \
  --upstream <checkout-Hermes-fixado>
```

`serve` fica em primeiro plano e usa o lock exclusivo nativo. Iniciar o processo
**preserva** a pausa persistente e não habilita o relay. `pause` solicita drenagem;
confira `control.drained=true` no status antes de encerrar o controlador durante
uma manutenção. `resume` exige `--expect-pause <episodio-atual>` e os preflights
existentes; não é uma aprovação de escopo ou consumo. `SIGTERM` em `serve`
encerra o dispatcher, mas sozinho não pausa nem mata workers separados. Não use
um PID antigo do status como autorização para sinalizar processos.

#### Supervisão macOS e parada econômica

`scripts/prepare_hermes_launchagent.py` recebe os mesmos `--source`,
`--expect-source`, `--python`, `--root` e `--upstream` e produz exclusivamente
`<raiz>/private/operations/dispatcher.plist`. Exige pausa e provedor desabilitado;
não carrega o serviço. Confira o plist com `plutil -lint` e seus argumentos.
Ele contém somente caminhos e digest, sem credenciais. Para o usuário logado:

```sh
launchctl bootstrap "gui/$(id -u)" <raiz>/private/operations/dispatcher.plist
launchctl print "gui/$(id -u)/ai.fabriquinha.<namespace>"
```

O controlador permanece em primeiro plano sob `launchd`, com o lock nativo.
Crash é reiniciado com intervalo mínimo de 60 segundos; saída normal ou erro de
configuração não dispara retentativa contínua. SIGKILL é classificado pelo
launchd como término intencional e também exige retomada explícita; não confunda
essa política com recuperação de toda forma possível de falha. Core dumps
ficam desabilitados. Veja estado e logs privados do
job; existência do plist/status antigo não prova processo vivo. Reiniciar não
remove pausa nem habilita inferência. Para iniciar também nos próximos logins,
instale o plist revisado, sem sobrescrever outro job, em
`~/Library/LaunchAgents/ai.fabriquinha.<namespace>.plist`. O registro apenas por
`bootstrap` não é uma promessa de persistência entre logins. Trocar a fonte
exige descarregar e substituir explicitamente esse job após drenagem.

Parada econômica completa, preservando homologação e volumes:

1. Execute `pause` pela entrada pública e confira `control.drained=true` em
   `status`. Pausa durante uma chamada não desfaz o consumo já enviado.
2. Confira no `launchctl print` o job/caminho da sua instalação; execute
   `launchctl bootout gui/<uid>/ai.fabriquinha.<namespace>`. Confirme que o job
   não existe mais. Não sinalize um PID copiado de arquivo antigo.
3. Execute `disable-provider --expect-pause <episodio-atual>` pela mesma entrada
   pública. Ela exige o lock exclusivo livre e drenagem, muda somente `enabled`
   na política e mantém contadores, holds e teto. O relay já carregado ainda
   precisa ser parado: não existe recarga de política em memória.
4. Com o Compose e env exatos da instalação, execute `stop model-relay` e
   confira `ps -a model-relay` como parado. Não use `down -v`, prune ou parada
   global do Docker.

Para retomar: carregue o controlador pausado; recrie somente o relay com política
desabilitada, confira `/status`, use o enablement existente com contador/teto
exatos autorizados, recrie o relay e somente então aplique `resume` com o episódio
atual. Aprovação de escopo continua independente. A prova
`qualify_source_operations.py --launchd` verifica fonte publicada, board vazio,
lock único e manutenção da pausa após crash/reinício sem chamadas ao modelo.

O runtime gerenciado verifica a fonte no início, antes de despacho e durante
as atividades do SDK. Corrigir a fonte exige outra cópia e manutenção; não
edite um export vivo. A fonte fixada não substitui o bundle de validadores nem
autoriza mudar seu contrato. O ciclo completo de upgrade/rollback continua em S6.

Para instalar o contrato de aceitação compartilhada antes do planejamento,
use a mesma entrada pública:

```sh
python3.14 -B scripts/run_hermes_runtime.py configure-acceptance \
  --source <privado>/runtime-source --expect-source <source_digest> \
  --python <python-do-SDK> --root <raiz-privada-da-instancia> \
  --upstream <checkout-Hermes-fixado> --expect-validation <bundle-atual>
```

A fonte deve conter o [ADR 0006](ADR-0006-SHARED-ACCEPTANCE.md) e seus validadores.
Exige pausa drenada, provedor desabilitado e ausência de cards de planejamento
ou entrega. Não muda o brief, não habilita consumo e não inicia o dispatcher.
O recibo preserva os bundles anterior e novo; não converte resultados antigos.
Uma instalação com trabalho já iniciado exige outro procedimento de migração,
ainda não qualificado — não apague cards para contornar a restrição.

A prova isolada de clone local limpo, board nativo novo, início pausado, lock
exclusivo, reinício, recusa de retomada obsoleta e detecção de alteração pode ser
executada com o Python do SDK, sem rota de modelo, credenciais ou jobs Docker:

```sh
<python-do-SDK> scripts/qualify_source_operations.py \
  --root <raiz-privada-nova> --repository "$PWD" \
  --revision "$fabriquinha_revision" --upstream <checkout-Hermes-fixado>
```

Essa prova não instala imagens, não qualifica execução paga nem entrega produto.
Ela também não qualifica o gerenciador de serviços do host ou o corte do legado.

**As seções numeradas abaixo preservam procedimentos do legado.** Os comandos
Multica, port2 e da ponte de revisão não são a instalação do caminho Hermes.
Para testes offline atuais, use os comandos do [README](../README.md).

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
O parser e a atestação também existem em fonte, sem roteamento instalado.
O coordenador e o despacho da correção agora estão ligados em fonte por flags
opt-in; `QUALITY_DELIVERY_REVISION_ENABLED` também é desligado por padrão.
Não habilite esses flags manualmente: faltam admissão/execução da correção,
revalidação, publicação e qualificação nativa. A candidata `20261024.37` apenas
compilou/importou os módulos, sem substituir o controlador instalado. O executor
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
