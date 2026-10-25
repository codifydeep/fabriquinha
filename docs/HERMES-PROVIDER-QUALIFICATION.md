# Provedor neutro: limites, qualificação e autorização

O caminho Hermes/Kanban possui agora `src/fabriquinha/provider.py`: relay pequeno
para OpenRouter, sem imports dos adapters históricos de ferramentas/schema,
fallback de modelo ou reparo de respostas. **Ainda não está instalado como rota
de produção nem libera a execução da equipe.**

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

Próximo: preparar instalação e objetivo pequeno S4, obter autorização explícita
da execução paga e usar GitHub/modelo reais. Telegram, segunda release/memória,
instalação limpa e cutover continuam pendentes. A implementação não introduz
outro scheduler, DB ou mecanismo próprio de retry.
