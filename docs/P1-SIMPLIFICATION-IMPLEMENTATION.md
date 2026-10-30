# P1 — implementação aprovada em 30/10/2026

Decisão do proprietário: manter Hermes + Kanban. O plano da auditoria de 30/10
foi aprovado; pequenas correções não dispensam revisão ou proteção das regressões.

## Matriz

A configuração já fornece `execution.reviewers` ao planejamento. Seus valores
são alternativas elegíveis, não uma lista de assinaturas cumulativas. O primeiro
ajuste explicita essa semântica no contexto compartilhado, sem alterar identidade,
seleção ou quantidade de revisores. Consulta técnica não cria um gate adicional.

Estado: instalado em 30/10 a partir de `03b5fea`, após pausa controlada, ausência
de workers ativos, backup SQLite com integridade verificada e exportação congelada.
Dispatcher retomado; doctor confirmou ready sem erros. A seleção de revisores
não mudou. A instrução se aplica às próximas execuções.

## Fixtures

Os observadores centrais de `AcceptanceTest.new_context` e o gate final de
`acceptance_evaluate` já detectam erros de console/pageerror. Nos dois novos
arquivos de aceitação, a concatenação das listas no setup captura apenas uma
cópia. Encaminhar à equipe uma correção técnica delimitada: eliminar a duplicação
ou preservar referências vivas, demonstrar que erro após setup reprova e executar
a suíte integral. Não editar snapshots da v0.3 nem converter resultados antigos
em validação da correção.

Antes do despacho, verificar o caminho de admissão para manutenção de teste de
release concluída. Se ele exigir incidente ativo, não fabricar falha/retries:
usar um novo objetivo de manutenção com escopo e evidências explícitos, sob o
contrato existente. Uma alteração necessária de contrato deve ser apresentada
como tal, não escondida na manutenção da fixture.

## Kanban

Próxima alteração: visão de consulta que explique a release vigente e seus
predecessores, mantendo o board nativo acessível. Derivar estado do grafo e do
recibo de aceitação. Não marcar predecessores como concluídos nem arquivar por
heurística de nome. Identificar claramente o dispatcher Fabriquinha e evitar
interpretar `Gateway: Off` como parada da equipe. Validar leitura sem escrita e
estado indisponível/antigo como desconhecido, nunca como saudável.

Nenhum novo serviço, banco ou orquestrador. Publicação do código não equivale à
instalação no runtime congelado. Registrar implantação e validação separadamente.

## Resultado da verificação de manutenção

A admissão instalada declara `frozen_python_test_revision=false` e
`Quality.correction_diff` rejeita revisão técnica Python congelada. Além disso,
a admissão de reparo exige incidente de implementação bloqueada/triage, ausente
na release concluída. Portanto, não foi despachado um objetivo destinado a falhar,
nem fabricado incidente. As fixtures permanecem inalteradas; P1 não está concluído.

Próximo passo técnico: qualificar uma autorização de manutenção com referência à
entrega concluída e escopo exato, reutilizando revisão independente e novo freeze.
Validar rejeição de arquivo fora de escopo, revisão obsoleta, autor igual ao revisor,
remoção de casos e bypass do observador central. Demonstrar erro tardio capturado
pelo harness, suíte completa e controle negativo antes do despacho real. Não
habilitar globalmente revisão Python apenas mudando o indicador de capacidade.
Não há necessidade de novo serviço ou de uma nova autorização geral do proprietário.

## Visualização instalada

O launcher acrescenta orientação dispensável à página nativa do Kanban, explicando
quem despacha, o significado dos cards históricos e o canal de comandos. Não
transforma estados nem declara saúde a partir de uma mensagem estática. Cinco testes
passaram, incluindo preservação de respostas 401, APIs, bloqueio de mutações e
WebSockets. Painel reiniciado isoladamente e orientação confirmada no navegador.
A visão resumida derivada de grafo/recibos continua pendente; esta etapa é apenas
orientação visual, não um novo painel de estado.
