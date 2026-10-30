# P1 — implementação aprovada em 30/10/2026

Decisão do proprietário: manter Hermes + Kanban. O plano da auditoria de 30/10
foi aprovado; pequenas correções não dispensam revisão ou proteção das regressões.

## Matriz

A configuração já fornece `execution.reviewers` ao planejamento. Seus valores
são alternativas elegíveis, não uma lista de assinaturas cumulativas. O primeiro
ajuste explicita essa semântica no contexto compartilhado, sem alterar identidade,
seleção ou quantidade de revisores. Consulta técnica não cria um gate adicional.

Estado: código preparado em `config.execution_context`; instalação ainda pendente
após validação e exportação da fonte congelada. Não afirmar que agentes em execução
já receberam a instrução nova.

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
