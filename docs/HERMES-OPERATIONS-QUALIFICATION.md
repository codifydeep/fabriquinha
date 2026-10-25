# Pausa persistente, drenagem e admissão

Data: 24/10/2026. Continuação do [serviço](HERMES-RUNTIME-QUALIFICATION.md) e da
[integração contínua](HERMES-INTEGRATION-QUALIFICATION.md).

Estado: **passou com SDK/Kanban/Docker reais e 19 respostas HTTP programadas
localmente**. Produção, chamadas pagas e migração continuam desabilitadas.

## Contrato operacional

Parar o processo `serve` continua significando reiniciar o dispatcher, não parar
workers saudáveis. A operação `pause` é diferente:

1. Grava uma barreira privada, atômica e persistente para projeto/upstream e um
   episódio específico. Não tem TTL e não desaparece por reinício.
2. Impede novos spawns. Uma corrida entre a claim e a barreira é recusada como
   indisponibilidade de infraestrutura pelo mecanismo nativo, sem gastar retry
   funcional. O lock operacional serializa a barreira com o spawn efetivo.
3. O SDK é interrompido pela API pública `hard_interrupt`. Ferramentas/gates
   também conferem a barreira. Comandos e testes já iniciados precisam encerrar
   ou atingir seus prazos; não se sinalizam processos por nome/prefixo.
4. A interrupção é preservada como recibo, não como falha técnica ou entrega.
   O run só é retomável depois da morte verificada do worker e do reclaim nativo,
   que conserva a fase de revisão e não consome uma tentativa funcional.
5. A retirada das sandboxes usa os mesmos intents e identidades já qualificados.
   A pausa não apaga arquivos, sessões, logs, snapshots ou histórico de falhas.

O marcador de drain do gateway upstream foi examinado, mas não serve para essa
pausa: expira após uma hora e pode ser ignorado após troca de instância. O novo
arquivo é **controle operacional**, não estado de cards, fases ou releases. Toda
transição de atividade continua no Kanban; não há outra base de workflow.

### Solicitada não é confirmada

- `control.paused=true`: a barreira foi solicitada e permanece ativa.
- `agents_stopped=true`: não existem workers/claims/sandboxes próprios pendentes
  conforme as identidades e os recibos; nenhuma nova chamada de modelo será feita.
- `drained=true`: além disso, o journal de execução/Docker/Git não tem efeitos pendentes.
- `busy`, `open_runs`, `unretired_sandboxes` e `pending_effects` mostram o que falta.

Não afirmar pausa efetiva enquanto `agents_stopped=false`. Uma requisição já
aceita pelo provedor pode ainda ser cobrada; interrupção do cliente não garante
cancelamento remoto. `drained` cobre o executor local, não serviços de terceiros
ou jobs GitHub Actions independentes.
A outbox é separada: a fila não impede drenagem e pode continuar enviando avisos
sem modelo enquanto a equipe está pausada.

O status é uma observação, não um substituto de revalidar liveness. O serviço
mantido em execução realiza a drenagem enquanto pausado. Se ele estiver parado,
repetir `pause` reobserva e reconcilia a mesma barreira, sem criar outro episódio.

### Retomada

`resume` exige o identificador do episódio atual, workers/claims/sandboxes
encerrados, preflight de recursos válido e rota de modelo autorizada. Um episódio
antigo não libera uma pausa posterior. A pausa do provedor pago continua sendo
outra fronteira: este comando não limpa o 402 nem levanta o bloqueio financeiro.

Efeitos pendentes podem exigir retomada para serem reobservados pelo mesmo
journal. Isso não autoriza refazer um efeito incerto. Uma barreira detectada
**antes do envio** produz `not_sent`: o relógio de observação começa no primeiro
envio real. Depois de qualquer envio, interrupção de um observador não transforma
o efeito em não enviado, não renova seu prazo nem autoriza reenviá-lo. Os prazos
persistentes de CI/publicação continuam sendo revalidados.

Um marcador corrompido ou de outro projeto fecha a barreira, mas não concede
autoridade de reclaim/retomada. Não é sobrescrito automaticamente. O diagnóstico
fica explícito para o operador.

## Admissão sem outro dispatcher

`doctor` consulta o pin/política do validador, presença da imagem de navegador
quando configurada, pelo menos 1 GiB livre e os perfis configurados. Não baixa
dependências, não executa produto e não chama modelo/GitHub/Telegram.

Recursos inválidos suspendem novos spawns, não a reconciliação nativa. São
reobservados a cada 15 segundos. A ausência de um perfil é diagnóstico, não um
bloqueio global: o dispatcher upstream verifica o perfil atual de cada card e
continua podendo trabalhar em outros papéis. Uma função mobile inativa não
interrompe uma versão web. Nunca usar um cache de perfil ausente como uma
segunda decisão de despacho.

O relatório `doctor` é uma consulta atual. O campo `admission` do serviço é datado
e pode ser `null` em uma instância nova do comando `status`; isso significa que
esse processo ainda não executou o preflight, não que os recursos foram aprovados.

## Uso em uma instalação qualificada

Use a raiz específica, nunca o home legado. Os comandos abaixo não são instrução
para iniciar chamadas pagas: o runtime ainda recusa projetos fora da qualificação.
O arquivo de rota é privado e não deve ser copiado para documentação ou Git.

```bash
PYTHONPATH=src .local-hermes-agent/venv/bin/python -m fabriquinha.runtime doctor \
  --root /CAMINHO/PRIVADO/DA/INSTANCIA --upstream /CAMINHO/HERMES/FIXADO
PYTHONPATH=src .local-hermes-agent/venv/bin/python -m fabriquinha.runtime pause \
  --root /CAMINHO/PRIVADO/DA/INSTANCIA --upstream /CAMINHO/HERMES/FIXADO
PYTHONPATH=src .local-hermes-agent/venv/bin/python -m fabriquinha.runtime status \
  --root /CAMINHO/PRIVADO/DA/INSTANCIA --upstream /CAMINHO/HERMES/FIXADO
PYTHONPATH=src .local-hermes-agent/venv/bin/python -m fabriquinha.runtime resume \
  --expect-pause ID_DO_EPISODIO_ATUAL \
  --root /CAMINHO/PRIVADO/DA/INSTANCIA --upstream /CAMINHO/HERMES/FIXADO
```

Pausa/retomada e reclaim geram avisos pela outbox existente, sem modelo. O
transporte Telegram real permanece não qualificado.

## Roteiro e limites da prova

`scripts/qualify_hermes_operations.py` usa SDK, SQLite, ferramentas e Docker
reais, mas respostas HTTP programadas. Interrompe uma chamada retida do autor e
outra do revisor, reinicia pausado sem rota, rejeita retomadas indevidas, restaura
um perfil temporariamente ausente e continua o TDD completo. Isso não comprova
julgamento de um modelo ou entrega de release.

A primeira tentativa foi encerrada como não aprovada: o cache de perfis ausentes
refusou um revisor que o dispatcher nativo já reconhecia como restaurado. A raiz
foi pausada, conferida sem workers/claims/efeitos e seu serviço exato encerrado
antes da correção. O cache passou a ser apenas diagnóstico; a decisão de perfil
continua nativa. Há testes de regressão dessa condição.

A segunda tentativa percorreu, sem reparo do operador durante a execução:

1. Autor escreveu o teste novo e entrou em outra chamada local retida. `pause`
   interrompeu o SDK, preservou o arquivo/sessão e liberou a claim por reclaim
   nativo. Não houve chamadas novas após a confirmação de drenagem.
2. O serviço reiniciou pausado e sem arquivo de rota. Uma tentativa de `resume`
   foi negada; o marcador não foi removido. A rota foi restaurada pela fixture.
3. O preflight informou revisor/mobile ausentes, sem bloquear o autor. Ao receber
   a entrega, o dispatcher aguardou o perfil do revisor sem consumir retry. A
   fixture restaurou o diretório; o despacho nativo prosseguiu imediatamente,
   sem falso cooldown vindo do cache.
4. A primeira revisão também foi interrompida numa chamada retida. O card voltou
   a `review`, não a implementação. O episódio anterior não pôde liberar a nova
   pausa. Revisor retomou sua sessão na revisão imutável.
5. Depois da retomada, houve solicitação de mudanças, correção pelo autor,
   congelamento independente, Green, controle negativo e revisão final. Os dois
   cards terminaram em oito runs: dois `reclaimed` e seis handoffs TDD válidos,
   sem `crashed`, `timed_out` ou bloqueio técnico.
6. Serviço/workers terminaram e todos os auxiliares próprios foram retirados.
   A raiz descartável foi deixada pausada/drenada depois da prova. Evidências,
   arquivos e sessões foram preservados. Não houve nova imagem, exclusão de
   volume, mudança em Toso ou ativação do legado.

O denominador é duas tentativas, uma aprovada neste escopo; a primeira não recebeu
aprovação retroativa. A fixture controla respostas e disponibilidade: **não é**
ensaio de julgamento/autoria por um modelo nem entrega de release.

Há 14 testes novos dessa fronteira: marcador persistente/escopado, corrupção,
retomada obsoleta, recursos, perfil não obrigatório/cache obsoleto, fence dos
gates, reconciliação sem spawn, reclaim só após morte, retenção da pausa do
provedor e distinção entre efeito não enviado/incerto. **139 testes do caminho
atual** passaram sem falhas ou skips. A regressão histórica passou com
4.523 testes e oito skips preexistentes; nenhum teste foi removido.

Falhas físicas de Docker/disco são simuladas em unitários: não derrubar o daemon
ou encher o disco do proprietário para testar admissão. Não se afirma segurança
contra remoção manual do arquivo de controle pelo administrador, nem instalação
portável, gateway Telegram ou liberação de um provedor pago.

O núcleo agora tem 16 módulos funcionais e 3.541 linhas físicas, incluindo a lane
S1 e `__init__`. O módulo adicional reúne controle operacional/admissão, requisitos
explícitos antes do consumo real; não é coordenador, novo serviço ou banco. O
desvio da meta inicial de 3.000 linhas continua visível. Não expandir esta camada
para reproduzir o broker antigo.

## Continuidade

As provas posteriores de brief/plano, aprovação exata e aceite integral estão em
[intake/release](HERMES-INTAKE-QUALIFICATION.md). A espera por provedor foi
conectada e qualificada separadamente em [provedor](HERMES-PROVIDER-QUALIFICATION.md).
Esses resultados não transformam esta prova de pausa em entrega autônoma.
Incidentes de integração e outras provas S5 continuam pendentes. Não acrescentar
outro scheduler ou uma recuperação por erro para preencher essas lacunas.

## Preparação isolada antes de S4

`scripts/prepare_hermes_project.py` prepara um home novo, board vazio e perfis
derivados da matriz. Não copia bancos, sessões, SOULs, skills ou credenciais da
instalação antiga; as instruções do worker continuam sendo os contratos explícitos
de fase, não uma promessa de que plugins antigos foram carregados. Um preparo
parcial não é sobrescrito nem retomado silenciosamente.

O [exemplo de projeto](../examples/python-http/project.example.json) contém as
nove identidades e a matriz de suplência. Repositório e hashes de imagem são
placeholders: substituir por valores próprios e imagens já qualificadas. Ter um
perfil mobile não qualifica uma toolchain mobile; esta stack continua Python/HTTP.

Com SDK/dependências e o upstream fixado já disponíveis, a forma de uso é:

```sh
python scripts/prepare_hermes_project.py \
  --root .local-simplification/my-project \
  --upstream /path/to/pristine/pinned-hermes \
  --project /path/to/project.json \
  --model provider/model \
  --provider-port 19390 \
  --max-calls 10000
```

O comando valida configuração, exige branch diferente de `main`/`master`, recusa
raiz existente e, dentro do checkout da automação, exige um destino ignorado pelo
Git. Grava a pausa antes de perfis/rota, política `enabled=false` e arquivos
privados. O token gerado é de cliente local, não chave OpenRouter. Não monta ou
consulta o medidor real, registra runner, cria branch/PR, inicia serviço ou chama
modelo. `preparation.json` distingue explicitamente preparo de instalação completa.

A prova na instalação de referência confirmou nove perfis, zero cards, estado
pausado/drenado, `provider_disabled` e doctor sem perfil/recurso ausente. A política
desabilitada é recusada antes até da consulta HTTP ao relay. Isso não concede
autorização de consumo nem é qualificação S6 de instalação limpa.

O proprietário aprovou substituir o runner por CI local fixo e status no GitHub,
somente na branch nova. O [bootstrap e seu primeiro CI real](HERMES-INTEGRATION-QUALIFICATION.md#status-obrigatório-real--25-de-outubro-de-2026)
já passaram; a `main` não mudou. O novo home tem fingerprint próprio para essa
política; não foi convertido silenciosamente o preparo anterior.

O [Compose do relay](../examples/python-http/compose.provider.yml) mantém o serviço
agrupado, sem socket Docker, chave em volume externo somente leitura e publicação
somente em loopback. A configuração de instalação permanece privada. O contador
existente não é criado ou zerado. `scripts/enable_hermes_provider.py` é uma ação
explícita do operador: confere política desabilitada, contador/teto exatos e
ausência de bloqueio, sem chamada ao modelo, aumento de teto ou remoção de hold.
Recriar o relay é necessário depois; a aprovação de negócio não habilita consumo.

Para S4 ainda é necessário refinar e aprovar o objetivo de produto e executar a
cadeia completa. Um workflow hospedado no GitHub ou preso aos caminhos históricos não
deve ser herdado como CI local qualificado. Não afrouxar checks para obter verde.
Após Produto refinar o objetivo, o CEO aprova o brief exato; o operador não
pré-escreve implementação, testes de feature ou pareceres para a equipe.

O contexto agora informa o contrato exato de saúde/identidade e o esquema JSON
do navegador, sem pré-escrever cenários da feature. QA malformado ou sem cobertura
dos critérios do pacote é recusado antes do Red e novamente antes do freeze.
Isso evita congelar testes que só seriam descobertos como inválidos após deploy.
O limite de 20 cenários é explicitamente um teto, não uma meta; a URL publicada
é fornecida pelo controlador e não fixa a porta externa em 8080. O campo `value`
da ação `fill` aceita texto vazio/espaços, pois são dados válidos de teste de
formulário, sem relaxar seletores, IDs ou asserções. Esse ajuste recebeu regressão
própria antes do aceite do brief; não foi introduzido no meio de uma implementação.
