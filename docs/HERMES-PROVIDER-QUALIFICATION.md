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
habilita o provedor. A rota de produção do runtime continua recusada até sua
integração explícita; não basta iniciar este relay.

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

Conectar política/admissão e espera por provedor ao worker nativo, preservando
sessão/fase e liberando capacidade, sem contabilizar indisponibilidade financeira
como falha funcional. Qualificar essa fronteira offline antes de iniciar S4
real com GitHub e modelo. Telegram, segunda release/memória, instalação limpa e
cutover continuam pendentes. Essa implementação não introduz outro scheduler.
