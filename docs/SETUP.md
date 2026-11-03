# Preparação do caminho Hermes + Kanban

Este guia descreve preparação e operação do núcleo atual. Não há instalador
completo qualificado para terceiros. Comece pelos testes offline no
[README](../README.md), sem credenciais. Consulte [STATUS](STATUS.md) para os
limites de qualificação. Não execute instaladores ou configurações retirados do
histórico como se fossem compatíveis com a versão atual.

As receitas abaixo usam configurações privadas por instalação. Exemplos de SHA,
imagem, episódio e caminho devem ser substituídos pelos valores verificados da
sua instalação; nunca copie uma autorização histórica.

### Ambiente Python dos agentes

O arquivo `scripts/requirements-hermes-agent.txt` contém os 47 pins do ambiente
leve dos agentes. Em 31/10/2026, todos coincidiram com o SDK da instalação de
referência. Não substituir esse arquivo pelos requisitos S1: estes pertencem
à prova inicial do Kanban/API e usam versões diferentes. O dashboard tem seu
próprio ambiente; não misturar suas dependências ao SDK.

Para provisionar um ambiente novo (download de pacotes, sem chamadas ao modelo):

```sh
python3.14 -m venv <venv-novo>
<venv-novo>/bin/python -m pip install -r scripts/requirements-hermes-agent.txt
```

A receita também foi executada em um venv novo em macOS ARM64/Python 3.14:
os 47 pins instalaram, e o preparador exportado do Git passou na admissão nativa
dos nove perfis, rejeição de configuração divergente e reinício pausado. Sem
chamadas ao modelo, jobs Docker ou alterações no GitHub. A prova foi repetida com um checkout esparso novo do Hermes público e uma
segunda raiz privada nova, também com sucesso. Ainda faltam ferramentas/imagens
e ciclo de entrega em ambiente independente. O checkout
Hermes deve estar limpo no commit
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`; o preparador recusa outro commit
ou alterações locais. Não copiar o home de uma instalação anterior.

### Checkout Hermes e prova de preparo sem inferência

A receita abaixo reproduziu o preparo em macOS ARM64 com o venv novo. Use caminhos
novos; o preparador recusa sobrescrever uma instalação. O checkout é esparso para
reduzir uso de disco e permanece separado de qualquer home de agentes.

```sh
git clone --depth 1 --filter=blob:none --sparse --branch v0.22.5 \
  https://github.com/NousResearch/hermes-agent.git <upstream-novo>
git -C <upstream-novo> sparse-checkout set \
  hermes_cli agent tools gateway cron pm hermes_plugins hermes_platform \
  plugins/kanban providers acp_adapter locales plugins/browser plugins/web \
  plugins/video_gen plugins/model-providers plugins/context_engine plugins/memory
git -C <upstream-novo> rev-parse HEAD
```

O último comando deve retornar o commit fixado acima. Para exercitar a preparação
pública, admissão de perfis, recusa de fallback/configuração divergente e reinício:

```sh
<venv-novo>/bin/python scripts/qualify_profile_admission.py \
  --upstream <upstream-novo> --root <raiz-privada-nova> \
  --image sha256:ID_DO_VALIDADOR --browser-image sha256:ID_DO_NAVEGADOR
```

Essa prova usa os IDs como configuração: **não constrói nem executa as imagens**.
Seu callback de despacho é simulado, não um worker real. O recibo deve registrar
nove perfis, provedor desabilitado, pausa preservada, nenhuma execução aberta,
zero chamadas ao modelo, zero jobs Docker e zero mutações GitHub. A raiz contém
cards de qualificação e não deve ser reaproveitada para uma equipe de produto.
O preparo normal de um projeto usa `prepare_hermes_project.py` em outra raiz nova.

### Operação no SDK provisionado do zero

Em 31/10/2026, `qualify_hermes_operations.py --managed-profiles` passou com o
venv e checkout esparso novos, reutilizando a imagem validadora local por ID.
Foram oito execuções nativas e 19 requisições HTTP programadas: pausa durante
autoria e revisão, preservação de arquivos/sessões, reinício sem rota enquanto
pausado, recusa de retomada obsoleta e TDD concluído após correção. Zero chamadas
ao modelo e nenhuma aprovação de entrega ou migração de produção.

A primeira tentativa foi recusada antes da execução: a fixture declarava o
contrato de perfis gerenciados mas criava configuração legada. A correção usa a
configuração canônica somente ao preparar uma fixture nova, antes do despacho;
não migra instalações existentes nem flexibiliza a admissão. A tentativa falha
permanece preservada e o resultado aprovado veio de outra raiz.

Essa prova reutiliza uma imagem local já qualificada. Não substitui build das
imagens a partir de um clone público, instalação por outro operador, integração
GitHub real ou entrega autônoma com modelo real.

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
No modo 2 já instalado, um reparo aditivo pode preservar o planejamento se ainda
não houver nenhum job de validação ou recibo de qualidade/diagnóstico, incluindo
baseline, Red e freeze. Após essa fronteira, outra migração seria necessária e
continua não qualificada — não apague cards, jobs ou recibos para contornar isso.

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

