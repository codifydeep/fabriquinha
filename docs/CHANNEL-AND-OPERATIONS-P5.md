# P5 — Canal real e operação reproduzível

Estado em 28/10/2026: S6 homologado com assistência. P5 em implementação;
nenhuma alegação de autonomia repetível. O proprietário escolheu reutilizar
seu grupo Telegram existente, com um único bot de entrada e avisos.

## Evidência inicial

- Clone limpo e exportação congelada passaram no ensaio de operações: dono
  único, reinício preservando pausa, recusa de resume obsoleto e fonte alterada.
- Esse ensaio não restaura dados de uma instalação com trabalho e não é um
  instalador completo. Nenhuma chamada ao modelo ou mutação GitHub foi feita.
- Bot e grupo existentes foram verificados por chamadas somente de leitura.
  O gateway legado está parado; não foi reativado nem consumiu mensagens.
- A outbox atual contém histórico não enviado. Habilitar transporte diretamente
  dispararia avisos antigos. Preservar esse histórico sem marcar como entregue.

## Implementação mínima do canal

1. Usar comandos de plugin do gateway Hermes fixado, que já fornece contexto
   de sessão e executa handlers síncronos fora do event loop. Não criar outro
   orquestrador ou interpretar aprovações com modelo.
2. Adaptar operações existentes de Intake: start, show e respond. Uma resposta
   exige identidade humana permitida, grupo autorizado, card e revisão exatos.
   Texto livre, mensagens de bots, respostas de outro grupo e aprovação antiga
   não concedem autoridade. Falha do handler deve retornar erro seguro, sem
   encaminhar o comando a um agente como aprovação alternativa.
3. Manter um único dono do dispatcher e um único consumidor Telegram. O gateway
   transporta comandos/avisos; não despacha workers nem concede gates técnicos.
4. Reutilizar Outbox para início, conclusão, impedimento, pergunta e entrega.
   Criar corte explícito de ativação; histórico anterior permanece arquivado
   como não enviado, nunca reclassificado como entrega confirmada.
5. Testar transporte com comandos reais de status antes de iniciar nova versão.
   Depois provar objetivo → pergunta → resposta vinculada → entrega no grupo.
   Falha de transporte não interrompe o trabalho; envio incerto não é repetido
   cegamente. Tokens e IDs de instalação ficam apenas em configuração privada.

## Recuperação e distribuição

- Ensaiar backup/restauração em raiz isolada com dados representativos: SQLite
  íntegro, recibos, objetos, outbox, pausa e contador preservados. Nunca executar
  duas instalações despachando o mesmo projeto ou usando a mesma cota restaurada.
- Provar upgrade e rollback de fonte enquanto pausado, recusando contrato
  incompatível. Reiniciar não pode repetir merge, consumo ou envio já confirmado.
- Reproduzir pela entrada pública e documentar dependências reais. Remover
  dependências legadas apenas após verificar imports e recursos necessários.
- Não copiar segredos, conversas, bases, snapshots ou worktrees para o Git.

## Saída e próxima fase

P5 termina somente com canal real de ponta a ponta e restauração demonstrada.
P6 exige duas entregas úteis comparáveis, com dois incrementos dependentes e
recuperação de falha controlada, sem patches do operador após o aceite.
Preservar o lobby S6 e o modelo atual. Não iniciar outro ensaio genérico para
substituir essas provas; não declarar o Truco completo entregue.

## Adaptador implementado, ainda não ativado

`channel.py` admite somente comandos explícitos de identidades humanas e destino
fixados em política privada. `channel_plugin.py` registra `/fabrica`, lê somente
ContextVars vinculadas ao pedido (sem fallback para identidade do ambiente) e
executa o Intake em subprocesso fixo com fonte verificada. Não usa shell, não
encaminha credenciais do modelo e não transforma erro em conversa com agente.
Testes cobrem destino/remetente incorretos, aprovação incompleta, identidade
estável de requisição, pausa e isolamento do subprocesso. Ainda faltam integração
com o gateway instalado, corte da outbox e validação real de ponta a ponta.

A prova `qualify_hermes_channel.py` passou com ContextVars reais do Hermes e
subprocesso real de status: remetente incorreto, ambiente obsoleto e mutação
durante pausa foram recusados; o ambiente do gateway permaneceu intacto.
Isso não substitui um comando recebido pelo Telegram.

A outbox agora permite arquivar somente chaves explícitas de mensagens nunca
tentadas. O conteúdo e motivo ficam preservados; o estado não é `delivered`.
Mensagens incertas/tentadas são recusadas, e novos avisos continuam enviáveis
após reinício. O corte deve ocorrer com o remetente parado ou pausado.
