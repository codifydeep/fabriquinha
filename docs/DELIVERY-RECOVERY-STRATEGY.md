# Retomar progresso: diagnóstico crítico e plano de execução

Referência: 3 de novembro de 2026. **Plano proposto, ainda não implementado.**
Este documento orienta a próxima execução; não altera os contratos instalados,
não autoriza orçamento adicional e não aprova nenhuma entrega.

## 1. Conclusão

A direção Hermes + Kanban continua adequada ao escopo atual. Já existem entregas
web delimitadas e uma prova histórica de dois incrementos sem intervenção após
o aceite. Entretanto, a recuperação de situações fora desse percurso ainda
depende de manutenção humana frequente. Não há evidência para declarar autonomia
geral ou distribuição pronta para terceiros.

O freio recente não é apenas lentidão do modelo. A interface de recuperação
impõe trabalho excessivo ao agente e contém uma lacuna concreta entre consultar
uma evidência, citá-la e efetivar uma decisão. Corrigimos partes dessa interface
e repetimos ensaios antes de provar o percurso completo. Essa estratégia consumiu
contexto e chamadas sem produzir transferência de responsabilidade verificável.

**Prioridade: fechar uma cadeia de recuperação completa, terminar a entrega
atual como assistida e só então repetir a prova de autonomia.** Não iniciar outro
produto, orquestrador, serviço de memória ou rodada de ensaios genéricos.

## 2. O que avançou e o que não avançou

| Dimensão | Evidência e limite |
|---|---|
| Entrega controlada | Há provas delimitadas de TDD, revisão, PR, CI, deploy, rollback e QA. Isso é patrimônio real, não prova para qualquer brief. |
| Dependências entre incrementos | Existe um ciclo histórico observado sem intervenção após o aceite. Falta repetibilidade diante dos novos incidentes. |
| Proteção de qualidade | Snapshots, autoria, revisões independentes e gates bloqueiam evidências insuficientes. Os bloqueios atuais não devem ser removidos para aumentar throughput. |
| Recuperação | Há mecanismos e testes, mas a cadeia recente não chegou ao autor/revisor. É o principal gargalo. |
| Diagnóstico | Relatórios acessíveis, retenção de erros e resumos melhoraram. Sua utilização pelo protocolo de decisão permanece incompleta. |
| Distribuição | A retirada de fontes legadas do caminho público reduziu ruído. Não simplificou, por si só, o fluxo de execução nem qualificou uma instalação limpa. |
| Custo e operação | Limites impedem gasto ilimitado, mas a indisponibilidade do provedor ainda gerou tentativas de despacho sem utilidade. |

Não atribuir uma porcentagem global a dimensões sem denominador estável. Medir
marcos comprovados e intervenções evita confundir volume de código, cards
concluídos ou testes verdes com autonomia.

## 3. Por que o progresso recente parou

### 3.1 Consulta e decisão têm contratos incompatíveis

`Diagnostic.report_page` permite ler um experimento histórico do mesmo incidente,
release e snapshot. Essa leitura corretamente não cria uma nova aprovação.
Porém `Diagnostic.decide` aceita a referência genérica `experiment` apenas quando
há experimento na execução atual. Uma leitura válida pode, portanto, ser seguida
por uma citação recusada. A ferramenta oferece informação sem um caminho claro
para usá-la na decisão.

Precisamos distinguir quatro coisas: **fato citável**, **evidência admitida para
uma ação**, **autorização da transição** e **aprovação da entrega**. Ler ou citar
um resultado antigo não deve conceder as três permissões seguintes.

### 3.2 A carga de contexto tornou-se parte do incidente

Houve relatório de aproximadamente 99 mil caracteres e contexto que permaneceu
acima de 90 mil tokens após compressão. Paginação resolve acesso, mas não resolve
o custo de localizar uma relação causal. O modelo passou a administrar relatórios,
schemas e tentativas de ferramenta, em vez de resolver o defeito delimitado.

A memória durável deve ser brief, decisões, grafo e recibos. A conversa é uma
memória de trabalho substituível. Uma nova tentativa técnica precisa de contexto
reconstruído a partir desses registros; uma retomada de transporte, por outro
lado, deve conservar operações já executadas e evitar duplicá-las.

### 3.3 Atividade não se converteu em progresso

Diagnósticos encerraram com `hold`, mas não transferiram o reparo ao autor. Um
`hold` pode ser correto; concluir esse card não conclui o incidente. A métrica
relevante é a próxima ação válida, com responsável e artefato, ou a eliminação
comprovada de uma hipótese — não a quantidade de diagnósticos terminados.

Esgotado o orçamento, ocorreram tentativas sem worker. Esse caso deve ser uma
dependência explícita do provedor, com retomada por mudança de estado; não uma
falha técnica repetidamente redespachada.

### 3.4 Defeitos distintos ficaram acoplados na investigação

Foram observadas causas diferentes: limite de recursos do servidor, requisição
fora de turno, resposta de polling obsoleta, consulta a sala já removida e espera
de fixture incompatível com o processamento de eventos Playwright. Uma hipótese
não deve ser apresentada como explicação de todas as falhas.

Há candidatos e controles offline úteis. Eles orientam o autor, mas não são
aprovações nativas. Uma suíte de 62 testes sem falhas também não basta quando o
QA de navegador continua recusando a entrega.

### 3.5 Nossa execução foi incremental demais na fronteira errada

As correções recentes resolveram sintomas reais e preservaram as proteções.
Mas instalamos ajustes parciais antes de testar a sequência completa
consulta → citação → decisão → sucessão. A suíte offline crescente não cobria
adequadamente esse uso composto. A condução manual de novos cards também afastou
o experimento do objetivo de autonomia.

Responsabilidade da manutenção: fornecer uma interface executável e testar o
handoff. Responsabilidade do agente: diagnosticar e decidir dentro dela. Não
atribuir ao modelo um bloqueio que o controlador torna impossível de resolver.

## 4. Simplificação proposta

### Um caminho de recuperação, com pequenas operações

Reutilizar controlador, journal, snapshots e Kanban. Não adicionar um protocolo
paralelo. A interface deve fornecer:

1. Estado atual, responsável, impedimento e operações realmente permitidas.
2. Resumo de evidências por cenário, requisição e resultado; detalhes sob demanda.
3. Referências citáveis já resolvidas pelo controlador.
4. Ação técnica com argumentos específicos e erros que indiquem a correção.
5. Materialização idempotente do sucessor e confirmação do handoff.

O agente não deve reconstruir hashes, inferir qual variante de schema está ativa
ou descobrir pela rejeição que uma ação anunciada é proibida. O controlador
continua responsável por conferir proveniência, identidade, escopo e permissões.

O primeiro reparo deve separar **citação histórica** de **experimento atual**.
Preservar inicialmente as exigências atuais de experimento para retomar ou
autorizar reparo. Não preencher implicitamente `self.experiment` com evidência
antiga. Eventual reuso de experimento como autoridade de transição exige contrato
separado e qualificação própria; não é necessário para corrigir a citação.

### Contexto pequeno e durável

Entregar ao diagnóstico apenas o objetivo aplicável, o incidente, a tentativa
recusada, diferenças relevantes e resumo causal. Arquivar a conversa anterior sem
apagá-la. Consultas filtradas e contagens devem preceder paginação de logs.

Versionar a identidade de contexto quando o contrato de ferramentas muda.
Distinguir isso de retry de transporte: não perder recibos de ferramentas
bem-sucedidas nem repetir efeitos externos. Não introduzir outra base de memória.

### Papéis sob demanda

Manter os perfis existentes. No incidente simples, o percurso principal é
CTO → autor → revisor independente. Tech Lead coordena dependências e incidentes
que atravessam componentes; Produto e CEO participam de decisões de comportamento
ou escopo. Não convocar nove perfis nem uma segunda aprovação de diagnóstico
apenas para repetir informação já formalizada.

### Preservar qualidade, reduzir cerimônia

Manter Red pertinente, congelamento independente, Green completo, controles
negativos relevantes, revisão, PR, CI no SHA exato e QA do deploy. Reparar um
teste técnico exige demonstrar preservação do comportamento protegido. Não
transformar contagem de assertions em prova semântica.

Eliminar repetição administrativa e experimento duplicado para mera leitura.
Não eliminar testes, observadores ou revisão para destravar throughput.

## 5. Plano com critérios de saída

| Etapa | Responsável | Trabalho | Critério de saída |
|---|---|---|---|
| A — Congelar o diagnóstico | Mantenedor da plataforma | Registrar um único pacote com falhas, referências, tentativas recusadas e próxima ação. Classificar o ciclo como assistido. | Um incidente atual e suas relações inequívocas; nenhum efeito ou worker pendente. |
| B — Fechar o contrato mínimo | Mantenedor | Corrigir citação histórica, apresentação das ações permitidas e contexto da tentativa; tratar espera de orçamento. | Uso válido completo por ferramentas reais, sem permissões novas implícitas. |
| C — Qualificar offline | Mantenedor | Reproduzir a sequência problemática por chamadas programadas aos handlers e Kanban nativo, incluindo reinício. | Decisão chega a um único sucessor com responsabilidade preservada; casos proibidos são recusados. |
| D — Instalar uma vez | Mantenedor | Backup delimitado, verificações de compatibilidade, instalação e conferência de versão. | Fonte instalada e cadeia offline correspondem; não iniciar chamada paga antes disso. |
| E — Reparar pelo time | CTO, autor e revisor | Uma investigação delimitada aproveita evidências existentes; autor produz nova revisão; revisão independente e controles negativos. | Transferência ao autor, correção revisada e falha original eliminada por evidência nova. |
| F — Concluir a entrega atual | Equipe | Suíte, revisão, PR/CI, deploy, QA e recibo de homologação. | Commit/PR/URL/evidências coerentes. Resultado explicitamente assistido. |
| G — Repetir autonomia | Equipe, após aceite do CEO | Uma entrega útil com dois incrementos dependentes, sem editar cards ou workspaces manualmente após o aceite. | Homologação e cadeia completa de autoria, revisão e recuperação; qualquer intervenção operacional invalida a qualificação autônoma desse ciclo. |
| H — Distribuir | Mantenedor | Clone limpo, instalação, restauração e prova em segundo ambiente. | Outra pessoa consegue instalar e reproduzir o percurso documentado. |

Sequência A–D forma **um lote de correção**, não quatro novos ensaios pagos.
Não abrir nova frente funcional enquanto E não transferir responsabilidade de
forma comprovada. Melhorias documentais pequenas podem acompanhar o lote sem
substituir seu critério de saída.

### Casos obrigatórios da etapa C

- Ler experimento histórico permitido, citá-lo e registrar decisão válida.
- Recusar evidência de outro incidente, release ou snapshot; preservar requisitos
  de atualidade para transições que os exigem.
- Uma leitura histórica não concede aprovação, escrita nem dispensa experimento.
- Exercitar os formatos que foram recusados, com erros acionáveis.
- Criar sucessor uma única vez após interrupção entre decisão e handoff.
- Recusar autorrevisão e aprovação obsoleta; manter incidente aberto até validação.
- Resumir erros relevantes apesar de grande volume de polling, preservando logs.
- Recuperar contexto sem reaplicar ferramentas já concluídas.
- Bloqueio financeiro/orçamentário não cria sequência de execuções destinadas a falhar.
- Testes verdes sem PR/CI/deploy/QA não permitem homologação.

Usar o mesmo caminho de execução instalado, com decisões programadas no lugar
do modelo. Essa prova qualifica protocolo e persistência, não raciocínio do LLM;
a etapa E continua necessária. Não fabricar uma aprovação para fazê-la passar.

### Quando parar e reavaliar

Não repetir a mesma ação rejeitada duas vezes sem evidência nova. Suspender essa
ação e manter responsável e próxima investigação visíveis; a release não termina.
Se a mesma fronteira de interface falhar novamente após o lote, revisar o desenho
desse módulo antes de instalar mais patches pontuais. Se a interface passar e o
agente ainda falhar no raciocínio, avaliar o mesmo caso de forma delimitada antes
de cogitar troca de modelo. Não reiniciar o projeto nem enfraquecer o teste.

## 6. Custo

- Fazer a preparação e o teste da cadeia offline antes de solicitar nova cota.
- Reutilizar logs e resultados para consulta; reexecutar somente para testar uma
  hipótese diferente ou satisfazer uma exigência explícita de evidência atual.
- Resumir dados deterministicamente, em vez de pagar ao modelo para paginar logs.
- Medir tokens de entrada, compressões e chamadas por transição útil. Limite de
  chamadas não é limite monetário; não prometer economia percentual sem medição.
- Manter modelo e saída máxima vigentes neste reparo. Reduzir contexto excessivo
  antes de reduzir saída e correr novamente o risco de truncamento.
- Reservar orçamento por etapa e parar quando a ação deixar de produzir informação
  nova. Não ampliar automaticamente cotas nem limpar bloqueios financeiros.
- Retirar helpers de teste obsoletos nas fronteiras de ciclo conforme o contrato
  Docker, preservando deploy, volumes, evidências, rollback e outros projetos.

## 7. Como acompanhar progresso de verdade

Publicar, por entrega: incrementos aceitos; tempo bloqueado e seu responsável;
handoffs concluídos sobre handoffs tentados; intervenções operacionais após o
aceite; chamadas/tokens por transição útil; experimentos repetidos sem mudança;
e vínculo final entre commit, CI, deploy e QA.

O próximo avanço visível deve ser **autor trabalhando a partir de decisão válida**.
Depois, **revisão independente da correção**; finalmente, **homologação**. Um novo
diagnóstico terminado, mais testes do controlador ou um worker ativo não serão
reportados como substitutos desses marcos.

## 8. Limite de autoridade deste plano

Esta auditoria documenta propostas. Não executou reparo, retomada ou chamada ao
provedor. O aceite do plano não substitui a aprovação de brief, exceção de
comportamento, orçamento adicional ou gate de entrega. A etapa B deve caber no
contrato existente; qualquer ampliação de autoridade será descrita separadamente
antes da instalação. Manter Hermes + Kanban e priorizar um módulo menor e coeso,
em vez de acumular outra camada de exceções.
