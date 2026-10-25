# Provedor neutro: limites, qualificação e autorização

O caminho Hermes/Kanban possui agora `src/fabriquinha/provider.py`: relay pequeno
para OpenRouter, sem imports dos adapters históricos de ferramentas/schema,
fallback de modelo ou reparo de respostas. A instalação isolada S4 agora tem uma
rota própria com autorização de consumo e teto restrito, descrita ao final.
Isso não aprova o brief nem comprova a entrega autônoma da equipe.

## Contrato implementado

- Política privada fechada: identidade do projeto, modelo exato, teto de chamadas,
  saída máxima, habilitação operacional e token de acesso local.
- Contador monotônico existente, reserva atômica antes do envio e formatos
  `calls.json`/`provider-pause.json` compatíveis com o medidor anterior. O relay
  não cria nem zera um medidor ausente ou corrompido.
- Uma tentativa HTTPS, sem redirects, streaming, lista de modelos ou retries.
  Ferramentas/mensagens/respostas passam sem adaptação semântica.
- HTTP 401/402/403 produz pausa persistente. Transporte incerto produz hold
  separado e impede uma segunda reserva até diagnóstico autorizado.
- O SDK recebe explicitamente o teto de saída da política. Pedido maior é
  recusado com 422 antes de reservar/enviar; não é mais reduzido silenciosamente.
  Isso evita um retry de truncamento que parece aumentar o orçamento, mas envia
  o mesmo teto ao provedor e gasta novamente sem a condição esperada pelo SDK.
- Metadados por tentativa preservam hash da requisição, teto solicitado/efetivo,
  status, finish reason, contagens de tokens e classe de erro. Não gravam chave,
  mensagens, respostas textuais ou argumentos das ferramentas. O JSON recebido
  pelo SDK continua sem reparo ou reescrita semântica.
- `/status` consulta somente metadados; admissão vincula projeto, modelo, política,
  teto e disponibilidade. Não lê a chave, consulta créditos nem remove bloqueios.
- A chave só é lida no envio autorizado. Logs não incluem prompts, chave ou
  respostas. Requisições e respostas têm limites de tamanho/tempo.
- Exclusão local de proprietário e lock do contador. O proxy legado não conhece
  o novo lock: é obrigatório confirmar que ele está parado antes de compartilhar
  o volume. Não executar os dois escritores simultaneamente.

Não é um gateway multi-tenant, um sandbox do próprio controlador nem uma
garantia de autorização de consumo. A autorização de negócio do brief não
habilita o provedor. O runtime aceita a rota de produção somente com
`provider-policy.json` privado e explícito, identidade do projeto, modelo/token
da rota e metadados do relay exatos. A implementação dessa admissão não instala
nem habilita uma política real. A instalação de referência continua sem agentes
pagos ligados; não basta iniciar este relay.

## Provas realizadas

### Opção de saída 16384 — preparada, sem ativação real

`OUTPUT_LIMITS` centraliza os limites aceitos pelo preparo, SDK e relay. A nova
opção 16384 é explícita; não altera instalações antigas, teto de chamadas,
modelo ou habilitação. O relay conserva o valor solicitado e recusa aumento
para 32768 antes da reserva. Sua disponibilidade no código não concede consumo.

A prova `qualify_hermes_provider_wait.py --max-output-tokens 16384` passou com
11 atividades SDK e 19 requisições locais. Conferiu o valor no transporte real,
402 após edição e na revisão, reinício, preservação dos contadores funcionais,
workspace e fase, e conclusão TDD. Zero chamadas OpenRouter. A instalação real
está parada com saída 8192; a proposta maior depende de aceite do operador.

Dois canários sintéticos reais (padrão/low) completaram chamadas de função,
reportando zero tokens de raciocínio. Eles não reproduziram a falha no contexto
nativo extenso e não qualificam uma entrega ou alteração de raciocínio.

Os testes locais verificam autenticação, identidade, teto, pausa preservada,
erro de transporte, exclusão de proprietário, ausência de fallback e nenhuma
reescrita do conteúdo. Os testes de canário simulam sucesso, novo 402 e recusa
antes de arquivar a pausa quando contador/chave não atendem às pré-condições.

`scripts/qualify_hermes_intake.py --neutral-relay` passou com Kanban, sessões e
SDK reais: nove atividades, dez requisições ao transporte local, perguntas de
Produto, aprovação exata, revisão Lead/CTO e retomada da mesma sessão. Uma pausa
402 injetada no medidor isolado bloqueou envio e admissão sem aumentar o contador.
Zero chamadas pagas nessa prova; respostas e decisões eram programadas.

Separadamente, `scripts/canary_provider.py` executou uma única inferência real
explicitamente autorizada: HTTP 200 e resposta exata `OK`, com até 128 tokens de
saída, sem ferramentas ou retry. Arquivou o marcador 402 anterior e preservou o
contador monotônico e teto. A primeira inicialização Docker foi recusada pelo
driver de logs antes de executar o processo; foi corrigido `max-file=2` para
compatibilidade com compressão. Não houve inferência nessa falha de partida.
O job encerrado foi removido automaticamente; recibos e arquivos de medição
continuam privados. Nenhum agente foi iniciado.

O canário demonstra acesso ao modelo naquele instante, não saldo suficiente
para uma release, confiabilidade do modelo sob ferramentas ou autonomia.
Falha/timeout de observação exige consultar a mesma execução e recibo, nunca
iniciar outro canário por hábito. Sem nova autorização, não repetir o envio.

## Próxima fronteira

### Admissão e espera conectadas ao worker

`runtime.model_route` valida a rota privada fechada (`custom`,
`chat_completions`, loopback `/v1`) e a política do relay. Em qualificação, uma
fixture local pode funcionar sem medidor; se existir uma política, ela também é
obrigatoriamente validada. Em produção, a política nunca é opcional. A fonte do
modelo nessa rota é essa política explícita, não as antigas configurações de
perfil do Hermes nem um fallback herdado.

Antes do spawn, indisponibilidade produz a recusa nativa de infraestrutura,
sem iniciar SDK. Durante a atividade, o watcher observa metadados, interrompe o
SDK e os handlers deixam de conceder ferramentas. O recibo `provider_wait`
preserva a identidade da fase; workspace e sessão continuam disponíveis. Um
handoff já validado não é desfeito por uma indisponibilidade posterior.

O serviço só libera a claim depois de comprovar a morte do processo pelo PID e
fingerprint nativos. Usa a primitiva de infraestrutura do upstream fixado,
sem patch: restaura `ready` ou `review`, preserva `consecutive_failures` e aplica
o cooldown nativo. Não usa `reclaim`/`unblock`, pois essas operações zeram o
contador. O outcome nativo se chama `spawn_failed`, inclusive no adiamento após
trabalho parcial; o recibo distingue esse caso da recusa antes de criar processo.
Não é conclusão, falha funcional nem nova autorização de consumo.

O status mostra a disponibilidade atual separada dos recursos do Docker. A
outbox recebe o impedimento com chave estável antes da liberação. Integração e
QA fixos não dependem do provedor de modelo. O cooldown espaça novas verificações
locais; não remove o marcador financeiro nem autoriza novas inferências. Não é
uma garantia geral de ausência de starvation sob toda falha de infraestrutura.

`scripts/qualify_hermes_provider_wait.py` passou com SDK, sessões, Kanban e TDD
Docker reais, usando somente um provedor HTTP local programado:

- 402 após edição do autor e outro na revisão independente.
- Reinício com cada bloqueio ativo, sem nova reserva ou envio ao provedor local.
- Um contador de falhas funcionais anterior preservado, sem incremento ou reset.
- Fase de revisão, arquivo do autor e sessões retomados; mudanças solicitadas,
  correção, freeze, Green e controles negativos concluídos.
- Onze runs nativos, dezenove envios locais, zero chamadas pagas. Cooldown do
  ensaio reduzido explicitamente para dois segundos; produção usa o nativo.
- Encerramento pausado/drenado, sem workers, sandboxes ou efeitos pendentes.

A primeira tentativa completou TDD, mas seu verificador procurou PID em uma
recusa que nunca criou processo. Permanece não aprovada. A segunda, em board
novo e sem reparos durante a execução, passou após corrigir o verificador; não
houve aprovação retroativa. Decisões eram sintéticas, não julgamento de modelo.

### Instalação S4 autorizada — 25 de outubro de 2026

O novo relay está em seu grupo Compose, sem socket e com chave em volume externo
somente leitura. O proxy antigo foi confirmado parado; o novo proprietário usa o
mesmo medidor sem zerar o contador. A política foi habilitada explicitamente após
conferir metadados, contador e ausência de pause/hold. O teto efetivo limita as
64 chamadas adicionais autorizadas e permanece abaixo do teto global anterior.
O modelo permanece Claude Haiku, sem fallback automático.

O relay sozinho não faz inferência. A execução começa pela atividade de Produto
e deve aguardar o brief exato aprovado pelo CEO. A nova branch tem CI local real;
PR de feature, julgamento independente, merge, deploy e QA pelos agentes ainda
são a fronteira S4. Telegram, segunda release/memória, instalação limpa e cutover
continuam pendentes. Não foi introduzido outro scheduler, DB ou retry de modelo.

### Primeiro planejamento real: limite encontrado

Produto refinou o brief com modelo real, e o CEO aprovou a revisão corrigida.
O planejamento seguinte produziu truncamentos repetidos sob o teto de saída.
A contenção do operador foi registrada: a tentativa não qualifica S4 autônomo.
Uma chamada terminou com transporte incerto; permanece consumida no contador e
seu hold foi arquivado apenas após autorização humana explícita, mantendo cópia
recuperável, exclusão do proprietário e ausência de escritores ativos. Não houve
repetição do envio nem reset do contador, PR de feature ou homologação de produto.

A análise encontrou o teto sendo reduzido silenciosamente pelo relay enquanto o
SDK podia tentar recuperações com saída maior. O contrato foi corrigido offline
conforme acima. O timeout de cabeçalhos também passou a respeitar o orçamento
total de 120 segundos; antes podia falhar após 30 segundos mesmo sem esgotá-lo.
Esse é um modo de falha encontrado no código, não prova retroativa da causa
exata da chamada incerta. Testes e uma fixture não comprovam que o modelo real
agora produzirá um plano; nova tentativa é necessária, com evidências separadas.

A nova prova offline de brief/plano passou com nove atividades SDK e dez chamadas
a respostas locais programadas, verificando o teto de saída em cada requisição.
O primeiro verificador não havia armazenado esse campo e falhou; sua tentativa
permanece não aprovada. A prova corrigida usou board novo, não aprovação retroativa.
Isso não é julgamento real de modelo nem validação do saldo disponível.

`Ledger.archive_uncertain` é uma API local do operador, não endpoint HTTP nem
ferramenta de agente. Exige contador/marcador exatos e identificador de autorização;
grava e sincroniza o arquivo antes de remover o marcador. Reentrada observa o
mesmo recibo, não limpa outra ocorrência e não repete inferência. A chave do
provedor não é necessária para esse arquivamento. Continuar exige nova política
e admissão válidas; a operação isoladamente não inicia agentes.
