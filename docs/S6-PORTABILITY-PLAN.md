# S6 — Instalação reproduzível e operação da equipe

## Ponto de partida

S4 tem uma entrega técnica sem intervenção após o aceite. S5 entregou a segunda
versão com dois pacotes, regressões preservadas, memória e recuperação reais,
mas registrou sete intervenções. Não repetir outro ensaio genérico nem tratar
os bancos privados existentes como instalador. O resultado e os limites estão
em [S5](HERMES-S5-QUALIFICATION.md).

O próximo objetivo é permitir a outra pessoa reproduzir o fluxo a partir do Git,
com seu repositório e credenciais. Manter Hermes + Kanban, um controlador e o
relay existente. Não adicionar orquestradores, filas ou bancos paralelos.

## Sequência e evidências

| Etapa | Trabalho | Evidência exigida |
|---|---|---|
| S6.1 — Atribuição auxiliar | Ativar conjuntamente o SDK e relay com endereço de atividade; preservar o contador e seus marcadores | URI/header consistentes, compressão atribuída, nenhuma nova chamada de worker sem escopo; histórico sem origem não é reatribuído |
| S6.2 — Preparação pública | Consolidar a entrada atual `prepare_hermes_project.py`, receitas de imagens e configuração de exemplo | Clone limpo, Hermes fixado e sem patches, imagens construídas por instruções públicas, raiz privada nova, sem UUIDs/caminhos/bancos da instalação anterior |
| S6.3 — Operação | Qualificar doctor/start/status/pause/resume e manutenção da fonte | PID/fingerprint verificados, um dono da instância, estado persistente, código imutável, pausa drenada e retorno idempotente |
| S6.4 — Outro repositório | Executar a entrada pública contra outro repo autorizado, com branch própria | PRs/revisão/CI reais, dois incrementos dependentes, QA/rollback e regressões no mesmo SHA; nenhuma edição manual do produto |
| S6.5 — Canais | Conectar intake, perguntas e entrega ao destino autorizado; manter execução independente de falha de envio | Mensagem recebida no canal real, resposta humana vinculada à pergunta/escopo corretos, fila persistente e deduplicação; recebimento não é presumido pelo enqueue |
| S6.6 — Upgrade e corte | Atualizar/reverter o código com preservação de estado e retirar serviços legados sem uso | Backup restaurado em isolamento, mesma cota e dados, proteção de leases, volumes/rollback retidos e nenhuma dependência operacional do legado |

S6.1 tem implementação e provas locais preparadas no
[ADR 0005](ADR-0005-VALIDATION-AND-ACCOUNTING.md), mas falta ativação conjunta e
qualificação do novo caminho real. Um relay antigo deve bloquear o novo SDK no
preflight, sem consumir chamadas. Não iniciar paid dispatch para descobrir uma
incompatibilidade já observável por metadados.

## Decisões para a execução

- Usar as entradas existentes e reduzir passos manuais. Não criar outro serviço
  apenas para reunir os comandos do operador.
- Fazer a preparação ser verificável e não iniciar inferência implicitamente.
  Mostrar pendências concretas em doctor, com comando de recuperação suportado.
- Gerar perfis a partir de configuração versionada. Validar divergências de
  ferramentas e rotas auxiliares antes de habilitar consumo; rotas explícitas
  fora do relay não pertencem à qualificação de herança do compressor.
- Congelar a fonte e qualificar SDK/relay como um conjunto. Preservar o bundle
  de testes; mudanças semânticas exigem sua migração própria.
- Identificar o repo/branch e orçamento antes da ativação. Não apagar ou modificar
  main de produto para facilitar o ensaio. Não transpor a aprovação de um brief
  para outro conteúdo/projeto sem autorização correspondente.
- Injetar falhas controladas em fixtures e pelo menos uma recuperação na execução
  relevante, sem matar processos alheios ou requisição financeira incerta.
- Auditar custos por diferenças entre checkpoints e escopos novos. Os 15 registros
  históricos sem atividade permanecem visíveis; não exigir apagá-los para uma
  janela nova demonstrar ausência de novas lacunas.
- Preservar projetos Toso/reforma, volumes, snapshots, deployment e rollback.
  Retirar somente recursos comprovadamente próprios e ociosos por seus IDs.

## Saída e limites

A conclusão exige instruções públicas suficientes para instalar em outro local,
operar e recuperar a equipe e entregar pela mesma entrada. Uma prova programada
com transporte falso não substitui essa entrega real. A aprovação técnica do
instalador também não dispensa os gates do produto ou a aprovação de negócio.

A instalação de referência encerrou S5 em 6.951/7.000 chamadas: restam 49.
Esses valores são um checkpoint, não uma autorização para novas instalações ou
um limite de dólares. Reservar o orçamento do ciclo antes da ativação; se não
couber, continuar offline e pedir a autorização específica necessária.

Só depois da evidência de S6, retomar o Truco por Produto a partir das informações
já fornecidas pelo CEO. A stack Python/HTTP atual não qualifica automaticamente
outros adaptadores, mobile, 3D, colaboração paralela ilimitada ou ausência universal
de starvation diante de dependências externas.
