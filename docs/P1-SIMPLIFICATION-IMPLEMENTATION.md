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


## Qualificação offline da manutenção — etapa estrutural

Implementado `observer_maintenance.observer_diff` e o comparador de snapshots.
Eles aceitam somente a substituição dos observadores locais duplicados pela lista
viva do observador central nos dois helpers existentes. Todas as outras árvores
sintáticas, casos, assertions, imports e condições permanecem idênticas. O snapshot
inteiro é comparado: mudanças no produto, descoberta, manifests, modos ou arquivos
fora dos dois caminhos são rejeitadas. Este comparador não concede autoridade e
não é um protocolo paralelo de execução.

Validação: seis testes novos passaram e a suíte completa teve 519 testes aprovados.
O teste de eventos simula duas páginas e comprova que erros tardios chegam à lista
central enquanto uma concatenação antiga permanece vazia. Isso é um teste unitário
do harness, não evidência de execução real em Chromium. Uma comparação em memória
com as duas fixtures entregues confirmou compatibilidade, sem gravar candidato,
workspace, snapshot ou recibo de produto.

A instalação continua sem permissão geral de revisão de testes Python. Não foram
consumidas chamadas ao modelo nem despachados cards de reparo nesta etapa.

### Integração ainda necessária antes do despacho

1. Vincular a manutenção à aceitação exata da release entregue, commit, snapshot e
   arquivos autorizados; recusar divergência da base ou outra release ativa.
2. Reutilizar o card de plano/revisão para o CTO validar o escopo, sem inventar
   incidente de falha nem reabrir a release homologada. A admissão não aprova testes.
3. Permitir o candidato somente no card de testes atribuído ao autor; produzir um
   recibo novo de revisão técnica. Preservar a referência ao Red histórico, sem
   apresentar Green de manutenção como novo Red de funcionalidade.
4. Vincular o freeze à revisão independente do candidato exato; verificar autoria,
   SHA, escopo e inventário novamente no caminho de CI. Não reinterpretar recibos
   antigos com a nova exceção.
5. Executar suíte completa e controle negativo de erro tardio em navegador real,
   inclusive depois do setup dos dois contextos. O reparo só será qualificado após
   essa prova e o ciclo de revisão; os testes unitários acima não o substituem.
6. Reutilizar implementação/Green, revisão, PR, CI local, implantação e QA existentes;
   publicar o novo recibo. Registrar reinícios com a mesma chave idempotente e
   nenhuma aprovação duplicada.

Esses itens permanecem pendentes. Não declarar o caminho instalado, o reparo
executado pelos agentes ou P1 concluído apenas pela existência do comparador.
