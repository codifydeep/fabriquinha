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

## Adaptador implementado e transporte instalado

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

## Transporte restrito

O runner genérico do gateway também inicia cron e aceita caminhos conversacionais.
Para manter a separação, `channel_gateway.py` incorpora diretamente o adaptador
Telegram nativo do Hermes e encaminha somente `/fabrica` ao mesmo handler.
Não implementa polling/reconexão próprios, não inicia cron, agentes ou dispatcher.
A autorização é aplicada antes e depois da construção do evento; bots, eventos
internos e eventos sem autoridade de controle são recusados. Mensagens pendentes
são preservadas no cold boot. A dependência Telegram usa a versão 22.8 fixada
pelo próprio upstream. O transporte está instalado como serviço supervisionado, em modo somente comandos.
O adaptador nativo conectou e registrou estado `running`; o teste de resposta
real pelo grupo continua pendente. Essa observação não qualifica o canal inteiro.

A consulta de ativação é `/fabrica@techlead_truco_poc_bot status` no grupo
existente. Consultas não acionam o modelo. Os gateways legados permanecem
parados; o corte do histórico da outbox e os avisos automáticos ainda precisam
ser ativados de forma controlada, sem disparar mensagens antigas.

## Restauração offline com dados

`qualify_state_restore.py` cria uma instalação sintética pausada, um card nativo
bloqueado, snapshot, recibo e aviso nunca enviado. Sob exclusão do dono do
runtime, verifica SQLite, copia e confere os hashes dos arquivos; abre a cópia
restaurada e verifica os mesmos dados e episódio de pausa. O ensaio passou com
19 arquivos, zero workers, chamadas de modelo ou efeitos externos.

O ensaio não é um comando de backup de produção. Ainda faltam contador real do
proxy, configuração secreta, caminhos de worktrees e reconciliação dos efeitos
externos de uma instalação real. Uma cópia íntegra não autoriza iniciar uma
segunda instalação nem restaurar uma cota antiga como saldo disponível.

## Corte de ativação instalado

O controlador e o relay foram atualizados para a fonte `6cc51421`, após pausa
com ausência de workers e efeitos pendentes, parada do dono e backup privado
legível. Foram arquivados 356 avisos nunca tentados, preservando conteúdo e
motivo. Nenhum desses avisos foi marcado como entregue.

O destino Telegram escolhido foi configurado e o despacho retomado. Um aviso
novo de retomada recebeu confirmação de envio, com uma tentativa. O contador
permaneceu em 7.318/8.500 chamadas; a homologação respondeu HTTP 200. Isso prova
o transporte de saída, mas ainda não a entrada humana nem o ciclo completo pelo
canal. O backup de manutenção não equivale a restauração de produção qualificada.

## Inspeção do backup real

`verify_installation_backup.py` extrai somente para uma raiz privada nova, recusa
symlinks/entradas externas, compara os arquivos com o arquivo compactado e abre
SQLite somente para leitura. A inspeção do backup de manutenção passou: 4.027
arquivos, 47 cards, 104 execuções encerradas, 61 snapshots e 387 recibos íntegros.
A pausa e o provedor desabilitado estavam preservados; contador salvo: 7.318.
Nenhum serviço da cópia foi iniciado, nenhum contador foi escrito no volume vivo.

A inspeção comprova recuperabilidade dos dados, não retomada operacional. Não
iniciar diretamente essa cópia: caminhos absolutos ainda podem apontar para a
instalação original. Uma recuperação real exige:

1. Drenar e parar o dono original e o consumidor do canal; confirmar identidade
   dos processos e efeitos pendentes. Não executar duas instalações do projeto.
2. Manter o contador/holds mais recentes do volume do provedor. Se esse volume
   foi perdido, comparar todas as evidências disponíveis e manter o provedor
   bloqueado até reconciliar consumo; nunca tratar backup antigo como nova cota.
3. Restaurar no caminho original ou migrar explicitamente todas as referências
   vinculadas. Validar fonte, upstream, contratos, credenciais e recursos Docker.
4. Reconciliar PR/SHA/status e implantação reais antes de repetir qualquer efeito.
   Avisos enviados ou incertos após o backup não podem voltar a ser enviados
   apenas porque a cópia os mostra como pendentes.
5. Iniciar somente pausado, verificar dono único e ausência de workers antigos;
   liberar o episódio exato de pausa apenas após essas verificações.

Esses passos ainda precisam de ensaio operacional com falha controlada. A
ferramenta de inspeção deliberadamente não oferece `resume` nem reinstala cota.

A qualificação sintética foi ampliada para iniciar o dispatcher real da cópia
restaurada, pará-lo e reiniciá-lo. Ambos os processos observaram o mesmo episódio
de pausa e estado drenado; a tentativa de segundo dono foi recusada. Nenhum
worker foi criado e o aviso original permaneceu pendente com zero tentativas.
Isso qualifica o reinício pausado da cópia sintética, não recuperação no meio de
uma entrega real. Essa falha controlada continua prevista no P6.

## Preparação da prova P6

A versão seguinte deve evoluir o lobby existente e preservar sua regressão. Foi
proposto ao CEO cancelar salas ainda aguardando oponente, seguido da propagação
do cancelamento aos demais navegadores e tratamento de uma entrada concorrente.
Esse objetivo ainda aguarda escolha; não é um brief aprovado nem autoriza iniciar
implementação. Produto deverá esclarecer e submeter o brief pelo canal real.

Após o aceite, congelar a versão da automação usada na prova. Registrar todo
patch operacional como intervenção e manter o denominador, mesmo se a versão
posteriormente for homologada. A falha controlada deve ser recuperável e ter
identidade verificável (por exemplo, reinício do dispatcher com worker vivo),
sem matar processo por nome ou reiniciar uma execução por timeout de observação.
As métricas vêm do Kanban, recibos, GitHub, implantação e ledger existentes;
não criar um novo coordenador ou outra fonte de verdade para medi-las.
