# Atualização Hermes v0.22.5 — compatibilidade qualificada

Solicitada pelo proprietário em 31/10/2026; qualificação integrada concluída em 01/11/2026. Instalação sob manutenção, com verificação pós-troca ainda necessária.

Origem: v0.22.0, `e06df9c2eae6901f4c88f464e0ae6e753c0428b8`.
Destino: v0.22.5, `bf0203a794a07aac3ff764972ab9087baa4e4f4e`.
Release: https://github.com/NousResearch/hermes-agent/releases/tag/v0.22.5

## Evidências até aqui

Checkout limpo separado e SDK novo provisionados. No subconjunto usado em macOS
Python 3.14, certifi mudou para 2026.10.19 e urllib3 para 2.8.0. psutil permanece
7.2.2: a entrada 8.0.0 do lock é específica de Android e não deve ser selecionada
pelo nome do pacote sem avaliar os marcadores de plataforma.

A prova de admissão nativa passou: nove perfis, recusa de configuração divergente,
recusa de fallback silencioso, reinício com divergência preservada, restauração da
admissão e pausa mantida. Zero chamadas ao modelo, workers ou mutações GitHub.

## Sequência restante

1. Qualificar execução real do SDK e continuação após truncagem na versão nova.
2. Qualificar a cadeia de entrega e revisão com os validadores fixados.
3. Qualificar migração reversível dos vínculos de instalação e controle: o runtime
   verifica o commit upstream em ambos. Não editar esses vínculos avulsamente.
   Exigir pausa drenada, owner exclusivo, backup legível, preservação de recibos,
   snapshot dos bancos e ledger externo intacto. Testar interrupção e rollback.
4. Provisionar e testar o dashboard e suas dependências separadamente. Explicar
   que Gateway Off é o gateway nativo e desabilitar visualmente o update não
   suportado na superfície somente leitura, sem liberar operações administrativas.
5. Instalar sob manutenção, verificar status/board/sessões e fluxo de recuperação.
   Registrar a entrega em andamento como assistida se houver intervenção.

## Novidades candidatas

Delegação configurável por perfil/modelo, comandos de plugins com escolhas e
melhorias de visibilidade de bots podem ser úteis. Avaliar depois da compatibilidade;
não criar outro dispatcher nem substituir os contratos de revisão e entrega.
Correções de Claude DirectSDK não demonstram solução para truncagem via OpenRouter.
Recursos de planos/limites não substituem a contabilidade local já autorizada.

A v0.22.0 continua sendo a versão ativa até a conclusão dessas validações.

## Qualificações adicionais

- SDK operacional: oito atividades nativas, vinte requisições ao servidor local
  programado, zero chamadas pagas. Continuação após limite de saída manteve
  ferramentas e handoff; isso não garante que um modelo real conclua toda tarefa.
- SQLite: a v0.22.0 reproduz a corrida de desaparecimento do WAL; a v0.22.5 a
  trata corretamente. Ambos preservam o dado e passam com conexão mantida.
  O teste agora reconhece explicitamente esses dois commits, sem patches upstream.
- Migração fria: `fabriquinha.upstream_upgrade` exige pausa drenada, owner
  exclusivo, backup integral conferido e checkout limpo. Alterações concorrentes
  são recusadas. Uma interrupção entre os dois vínculos retoma a mesma migração.
  A reversão dos vínculos só serve antes de outras alterações no estado; após
  migração de schema, usar restauração fria verificada, nunca apenas trocar SHA.
- Dashboard compilado do checkout fixado; API de status e Kanban autenticado
  responderam em instância sintética. O wrapper conserva o estado nativo do gateway
  e anuncia `can_update_hermes=false`: a interface de consulta não oferece uma
  ação administrativa que seria recusada. A orientação aparece também na página
  inicial e em System. Nenhuma mutação foi liberada.

## Avaliação de utilidade e simplificação

Prioridade imediata: correções SQLite e dependências, mantendo os contratos já
qualificados. A atualização não resolve por si só o incidente técnico da entrega
em curso e não justifica apagar histórico ou zerar retentativas.

Avaliar depois: comandos de plugins com opções podem simplificar o aceite de
briefs, desde que conservem card, revisão exata e identidade do CEO. A delegação
por perfil/modelo pode reduzir customização no futuro, mas só após demonstrar
preservação de revisão independente, autoridade persistente e limites de chamadas.
Não ligar dois dispatchers nem migrar handoffs por conveniência de interface.

As notas oficiais citam visibilidade de bots em grupos do **Desktop**, não uma
correção demonstrada do nosso Telegram. Também citam Claude **DirectSDK**; nosso
uso de OpenRouter não deve ser declarado corrigido por essa nota. Não ativar MCP
webhooks experimentais, fallback por limite ou novos serviços para esta atualização.

## Pausa solicitada pelo proprietário

Atualização interrompida antes de qualquer migração de produção. O ensaio integrado
foi pausado durante integração: sem workers vivos nem runs abertos, mas com um
efeito Docker pendente preservado. Dispatcher e dashboard isolados foram parados;
não há recibo de aprovação ponta a ponta desta versão. Antes de retomar, reconciliar
o efeito existente, sem repetir uma operação Docker de resultado incerto.

Suite offline: 557 testes aprovados; nove testes do wrapper do dashboard aprovados.
A migração sintética abriu no SDK novo mantendo a mesma pausa. Código e documentação
desta etapa permanecem em preparação, sem publicação ou troca do runtime ativo.

## Retomada em 01/11/2026

O efeito de rollback interrompido foi conciliado por observação do container
saudável com o mesmo artefato e identificador de efeito. A função de envio foi
substituída por uma recusa no procedimento de conciliação: nenhum Compose foi
reenviado. Após todos os efeitos estarem concluídos, o ensaio foi retirado pelo
procedimento de propriedade exata, com logs e snapshots preservados.

Antes da troca, a produção foi pausada e drenada. Backup frio conferido por
manifesto, com dez bancos íntegros. Uma cópia isolada desse backup abriu no
runtime novo mantendo os 131 cards (inclusive conteúdo, responsáveis e estados),
os 269 runs e a pausa. A verificação do backup SQLite usa `mode=ro&immutable=1`
e fechamento explícito para não criar sidecars dentro da cópia preservada.
O ledger externo de chamadas não participa da migração.

Para instalações existentes, `upstream_upgrade.prepare` só admite a origem e o
destino fixados, pausa drenada e checkout limpo. Parar também dashboard e canal
antes da preparação. Guardar suas configurações separadamente. `apply` compara
novamente todo o estado com o backup e modifica apenas os dois vínculos upstream,
conservando a pausa. Não editar referências manualmente para contornar essa
verificação. Depois de abrir a versão nova, a restauração de dados exige o
procedimento frio; a reversão simples dos vínculos deliberadamente recusa drift.

## Qualificação integrada concluída

Dois incrementos dependentes concluídos, onze atividades SDK e dezenove requisições locais programadas, zero chamadas pagas. Revisão independente por perfis, TDD, regressões, integração, implantação, rollback, restauração e QA passaram. O ambiente descartável foi retirado após preservar as evidências. GitHub e autores são programados neste ensaio: isso qualifica compatibilidade operacional, não comprova uma nova entrega autônoma do produto.
