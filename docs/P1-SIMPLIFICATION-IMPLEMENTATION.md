# P1 — simplificação aprovada em 30/10/2026

A arquitetura permanece Hermes + Kanban. Pequenas correções continuam sujeitas à
revisão independente e à proteção das regressões.

## Matriz — instalada

`config.execution_context` esclarece que os valores de `execution.reviewers` são
alternativas elegíveis, não assinaturas cumulativas. O controlador seleciona um
revisor independente por handoff; consulta técnica não cria outro gate.
Identidades, seleção e quantidade de revisores foram preservadas.

## Manutenção das fixtures — mecanismo instalado; entrega em andamento

Nos dois arquivos de aceitação novos, a concatenação de listas de erros no setup
produz uma cópia. Os observadores centrais de `AcceptanceTest.new_context` e o gate
final de `acceptance_evaluate` já protegiam a execução; a correção elimina a
redundância enganosa, sem invalidar a homologação anterior.

O [contrato delimitado](OBSERVER-MAINTENANCE.md) permite somente a substituição dos
helpers por referências à lista viva do observador central. Casos, assertions,
imports, outros helpers, manifests e produto permanecem iguais. Não foi habilitada
revisão geral de testes Python congelados.

O operador identifica a aceitação entregue e os caminhos exatos. A equipe reutiliza
o brief original como escopo histórico, sem fabricar novo aceite do CEO ou um
incidente de falha. Lead e CTO planejam/revisam; QA produz a revisão; outro perfil
congela o candidato exato. Green, controles, revisão, PR, CI, implantação e QA
continuam obrigatórios. O histórico e os snapshots anteriores são preservados.

O objetivo real foi admitido e o Tech Lead iniciou o planejamento pelo dispatcher.
As fixtures do produto não foram editadas manualmente. A primeira revisão real
interpretou incorretamente o alvo como helper do framework. O contexto foi então
explicitado com os helpers originais dos dois arquivos autorizados e a exceção
exata; cards, plano e revisão foram preservados. Este ciclo de manutenção é
assistido por essa correção da plataforma após o início. A entrega do reparo ainda
precisa fornecer evidências próprias; não declarar P1 concluído.

### Validação do mecanismo

- Suíte offline: 535 testes aprovados, incluindo escopo, snapshots completos,
  revisão obsoleta, autoria, jobs de outra execução e produto imutável.
- Kanban nativo isolado: admissão repetida e reconstrução do controlador preservam
  um plano e um grafo, com revisão separada do CTO. Papéis programados, sem modelo.
- Chromium real: quatro jobs isolados demonstram comportamento normal e erro
  tardio após setup de dois contextos. O observador central bloqueia o erro na
  fixture antiga; a assertion preservada também falha na fixture corrigida.
- A primeira prova de navegador falhou por health/identity incompletos na aplicação
  sintética. A fixture foi corrigida e a prova completa repetida. Isso não alterou
  testes ou implementação do produto.

Instalação executada com pausa, ausência de workers ativos, backup SQLite com
integridade conferida e fonte congelada. Dispatcher e canal retomados; doctor
confirmou a capacidade restrita sem erros. Modelos e limites não foram alterados.

## Kanban — orientação instalada; resumo ainda pendente

O painel nativo mostra uma orientação dispensável que distingue o dispatcher
Fabriquinha do gateway nativo e explica que cards históricos não significam
trabalho ativo. Autenticação, consulta somente leitura e bloqueio de chat/terminal
foram preservados. A orientação foi confirmada no navegador e tem cinco testes.

Ela não é um indicador de saúde nem um resumo da release. A visão resumida derivada
do grafo e dos recibos permanece pendente. Não alterar cards históricos para
melhorar aparência; estado ausente ou antigo deve aparecer como desconhecido.

Nenhum novo serviço, banco ou orquestrador foi introduzido. A próxima comprovação
é a entrega real da manutenção pela equipe, seguida da melhoria de visualização.
