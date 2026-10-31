# Balanço do plano e sequência executável — 31/10/2026

Complementa a auditoria `EXECUTION-REVIEW-2026-10-31.md`, sem substituir seu
histórico. Esta revisão não inicia agentes, não aprova brief e não altera gates.

## Parecer

A cadeia de entrega existe e produziu resultados reais. O problema restante não
é construir outra equipe, mas demonstrar que a mesma equipe continua entregando
quando o produto cresce e a plataforma muda. Manter Hermes + Kanban e o modelo.
Não recomendar outro recomeço, orquestrador, serviço de memória ou novos papéis.

A v0.3 permanece uma entrega autônoma observada. A entrega posterior de saída e
reposição foi homologada em dois incrementos, mas é assistida. Corrigir a
plataforma depois do aceite foi necessário para entregar; isso também impediu
que o ciclo comprovasse autonomia integral. O segmento final recuperou falhas
sem nova intervenção, o que é progresso, não reclassificação do ciclo inteiro.

O recibo final confirma `HOMOLOGADA`, `assisted=true`, aprovação de entrega e
commit `a731d2d6588d5c52121584d5cf8056c7074aea2d`. A auditoria anterior verificou
43 testes, 41 casos de navegador e preservação dos 15 arquivos do baseline.
Esses resultados não foram reexecutados nesta análise. O status persistido estava
atualizado, dispatcher running, sem cards em execução ou issues internas. Cards
antigos em triage/blocked/todo não devem ser interpretados isoladamente como
trabalho corrente: o grafo sucessor e o recibo determinam a situação da release.

## Execução do plano

| Frente | Situação | Evidência e pendência |
|---|---|---|
| A: visão operacional | Implementada e verificada na rodada anterior | Commit 08e01954; resumo somente leitura, freshness, homologação por recibo, classificação assistida, responsáveis e avisos. O aviso incerto foi classificado como histórico; recebimento permanece desconhecido. |
| B: compatibilidade | Parcial | Leitura histórica, isolamento de escrita, rejeição de bundle antigo no gate atual e retomada idempotente passaram em prova isolada. Falta uma prova consolidada de atualização entre duas releases e todos os consumidores seguintes. |
| C: repetibilidade útil | Pendente | Nenhum novo brief de motor do Truco aprovado. A saída/reposição assistida não satisfaz a próxima comprovação sem intervenção. |
| D: operação e distribuição | Parcial | Restore sintético reinicia dispatcher pausado e preserva estado. O próprio resultado não qualifica restore de produção nem reconciliação de efeitos externos. Falta instalação por outra pessoa/ambiente. |
| E: expansão | Pendente e posterior | Regras completas, persistência, 3D e mobile precisam de escopo e qualificação próprios; não são bloqueadores para demonstrar autonomia no escopo atual. |

O status e roadmap estavam atrasados quanto à frente A; foram corrigidos. Não há
novo salto de prontidão: manter **80–85% no escopo Python/HTTP local**. A régua
anterior continua válida: cadeia 95%, qualidade 92%, recuperação 75%, memória e
continuidade 88%, canal 85%, operação/distribuição 60%. São estimativas subjetivas,
não medidas de esforço restante nem probabilidade de sucesso. Não aplicar esses
percentuais à promessa de desenvolver qualquer software ou ao Truco completo.

## Onde a execução acertou e onde falhou

Acertos: evidências imutáveis, revisão independente, regressão preservada,
separação entre teste verde e homologação, integração por SHA e classificação
honesta de intervenção. Não simplificar eliminando esses controles.

Falhas: correções estreitas passaram por testes locais sem exercitar o consumidor
seguinte; regras do brief foram aplicadas indevidamente ao histórico cumulativo;
diagnósticos receberam contexto que omitia a submissão rejeitada; recuperação
repetiu operações cujo problema era a plataforma. Não atribuir esses problemas
ao modelo nem ao CTO do produto. Um agente não deve editar seus próprios gates.

O acúmulo de exceções de recuperação é dívida real. A contagem anterior de 10.773
linhas em src/fabriquinha ilustra crescimento, mas reduzir linhas não é critério
de sucesso. Primeiro consolidar cenários cobertos; depois remover duplicações
comprovadas. Uma grande refatoração agora dificultaria atribuir novos resultados.

## Próximos passos, em ordem

### 1. Fechar B sem novo harness

Responsável: mantenedor. Estender `scripts/qualify_hermes_release.py`, que já tem
continuidade entre releases, em vez de criar outro protocolo. A variação atual
de bundle por comentário antes dos testes verifica identidade, mas não basta
como atualização entre releases concluídas.

Construir duas releases no ambiente descartável: homologar a primeira com bundle
A, instalar B e entregar a segunda preservando regressões. Exercitar leitura da
primeira, Red/freeze da segunda, publicação/CI, seleção de rollback, implantação,
QA e fechamento. Rejeitar bundle estrangeiro, SHA divergente, revisão antiga e
evidência antiga apresentada como aprovação nova. Interromper uma transição
durável e retomar sem duplicação. Reaproveitar a prova histórica existente.

Saída: relatório único que vincule cada cenário a seu resultado e identifique
autores sintéticos, GitHub simulado e Docker real onde aplicável. Uma prova
determinística não se transforma em autonomia de agentes nem CI GitHub real.
Executar uma vez após as mudanças; repetir apenas em caso de falha ou alteração
relevante. Não abrir outra série genérica sem hipótese delimitada.

### 2. Preparar e executar C com a plataforma congelada

Responsáveis: Produto/CEO para escopo; Lead/CTO para decomposição e arquitetura;
equipe para execução. Produto propõe uma pequena fatia verificável do motor de
regras, com dois incrementos dependentes. A variante e seus comportamentos serão
explícitos no brief; esta auditoria não escolhe regras nem aprova esse brief.
Continuar na stack qualificada, sem introduzir 3D/mobile nesta prova.

Antes do aceite: B aprovado, configuração e fonte fixadas, baseline e rollback
legíveis, preflight sem pendências e orçamento conferido. Depois: nenhuma edição
manual da plataforma, cards, testes ou workspaces. Recuperação técnica normal
fica com a equipe. Defeito de plataforma fica com mantenedor; qualquer intervenção
necessária reclassifica o ciclo como assistido antes da alteração.

Saída: homologação com PR, CI, QA implantado, regressões e recibo; ledger de
intervenções verificável. Buscar duas entregas úteis consecutivas nessas condições
para evidência inicial de repetibilidade. Não inventar funcionalidades apenas
para atingir uma contagem nem alegar confiabilidade estatística com dois ciclos.

### 3. Qualificar D em isolamento

Responsável: mantenedor/DevOps. Escolher um único efeito externo com janela de
incerteza reproduzível, por exemplo deploy criado antes de seu recibo persistir.
Interromper e reconciliar pela identidade real do recurso; provar que não houve
segundo deploy, aprovação fictícia ou perda de consumo registrado. Depois testar
restauração completa e retomada cercada por proteção contra duas instâncias
escritoras. Não usar o ambiente vigente como laboratório destrutivo.

Saída: provas antes/depois e limites explícitos. Em seguida, instalar uma versão
congelada em outro ambiente/repositório usando somente README e configuração de
exemplo; idealmente com outro operador. Registrar todos os passos privados que
faltarem no manual e corrigi-los. Essa etapa pode avançar em paralelo à preparação
do brief, sem alterar a plataforma de um ciclo já aprovado.

### 4. Expandir E por necessidade de produto

Após a comprovação inicial, avançar no Truco. Persistência, segurança da sessão,
frontend/3D e mobile entram como capacidades com critérios próprios. Não declarar
que a prova do lobby qualifica estas capacidades. Observabilidade de produto
entra por pergunta concreta, hipótese e uso dos dados, não por adicionar bots.

## Simplificação e economia

- Uma projeção do estado corrente no Kanban; documentos de status resumem essa
  realidade e não criam outra autoridade. Histórico continua preservado.
- Contexto de recuperação: tentativa exata rejeitada, causa, evidência nova e
  próxima operação permitida. Uma suíte verde sem relação com a causa não justifica
  repetir integração nem consumir outro diagnóstico do modelo.
- Separar manutenção de plataforma e recuperação de produto. Evitar ensinar ao
  time mais exceções operacionais a cada bug do controlador.
- Reusar verificações determinísticas e resultados com identidade completa
  idêntica. Manter CI, controles negativos e QA, que verificam coisas diferentes.
- Medir chamadas/custo por release e por recuperação, intervenções e tempo sem
  progresso. Lacunas de contabilização devem aparecer como desconhecidas.
- Não mudar o modelo nem ampliar teto por padrão. Verificar saldo e reserva
  apenas antes de execução paga; esta análise não faz chamadas ao provedor.
- Aplicar a limpeza Docker já contratada na fronteira dos ciclos, sem novo
  serviço de limpeza, sem prune e preservando evidências, rollback e terceiros.

## Critério para parar de preparar e voltar a entregar

Concluir B é a próxima tarefa concreta. Quando passar, encaminhar o brief de C;
não esperar distribuição perfeita para produzir valor. Após o aceite, observar
a equipe em vez de conduzir seus passos. A autonomia pretendida é recuperação
dentro de limites e escalonamento correto, não ausência absoluta de bloqueios
externos ou autorização irrestrita para contornar contratos.

Limites da verificação: leitura de fonte, documentos, status e recibos locais.
Nenhum novo teste pago, mudança de modelo, reinício ou alteração de produto. As
consultas HTTP locais desta análise foram impedidas pelo sandbox; a URL indicada
é a do recibo, não uma nova afirmação de disponibilidade. Os testes anteriores
citados permanecem evidências anteriores, não uma execução nova nesta auditoria.


## Atualização de execução posterior ao balanço

Esta seção registra execução posterior; a tabela acima preserva o diagnóstico
que originou o plano. O status corrente detalhado continua em `STATUS.md`.

- **B concluída no âmbito determinístico:** duas releases, mudança real de bundle,
  leitura histórica preservada, QA atual, rollback e retomada foram exercitados.
  Autores e GitHub são programados; não é prova nova de autonomia do modelo.
- **C preparada, não autorizada:** Produto revisou o brief antes do aceite. O
  escopo proposto tem mão única e pedido de Truco em dois incrementos; as regras
  simplificadas de empate dependem de decisão explícita. Não iniciar por uma
  autorização genérica de continuar a manutenção da plataforma.
- **D avançou:** reconciliação de Compose após perda de confirmação e restauração
  isolada preservaram o efeito sem duplicar criação. Exportação pública passou
  nos 548 testes do núcleo sem site-packages. SDK provisionado em venv novo e
  checkout Hermes esparso novo passaram em preparo de perfis e operação real
  com respostas locais (oito execuções, 19 requisições, zero chamadas pagas).
  Uma fixture legada precisou usar a configuração canônica de perfis; a tentativa
  falha foi preservada e a segunda terminou. Não houve mudança do runtime ativo.
- **D ainda não concluída:** falta reprodução das imagens e cadeia completa em
  ambiente independente, além de recuperação com contabilidade e pausas do
  provedor e exclusão de um segundo escritor. A inspeção de backup existente
  apenas verifica integridade e lê um contador fornecido; não instala esse
  contador, não restaura o relay e não prova reconciliação de consumo.
- **E permanece posterior**, orientada por requisitos aprovados do produto.

Próxima ação operacional: obter o aceite exato de C e observar a execução sem
intervenções. Enquanto isso, D pode avançar somente com hipóteses delimitadas e
raízes descartáveis; não repetir ensaios verdes nem construir outro controlador.
Para contabilidade, a prova deve usar o ledger real com chamadas locais simuladas,
conservar marcadores de bloqueio, rejeitar rollback do contador e provar exclusão
de escritores. Não restaurar uma cópia antiga sobre o provedor em uso.


### Diagnóstico isolado do ledger de recuperação

Uma prova temporária com `Ledger` real, sem rede ou credenciais, reservou a
chamada 8 e marcou 402 na raiz original após copiar o estado com contador 7.
A cópia aceitou outro owner e reservou sua própria chamada 8, sem conhecer o
bloqueio posterior. Isso é consistente com locks locais por diretório; não
constitui prova de segurança contra cópias da raiz. Nenhum ledger real foi tocado.

Consequência: a futura restauração não pode ativar o ledger copiado do backup.
Deve reusar a autoridade atual de consumo e seus marcadores, adquirindo o mesmo
lock de owner antes de admitir o relay restaurado. Se essa autoridade foi perdida,
a retomada deve permanecer recusada até reconciliação explícita; nunca assumir
zero ou confiar no contador antigo. Não adicionar sincronização distribuída:
qualificar primeiro a recuperação local com um único ledger preservado fora da
raiz restaurável. O procedimento ainda precisa ser implementado e testado.


A extensão de `qualify_state_restore.py` passou usando o ledger real em raiz
sintética externa à árvore restaurada: contador 8 e bloqueio 402 posteriores ao
backup permaneceram, nova reserva foi recusada e um segundo owner da mesma raiz
não foi admitido. O dispatcher restaurado reiniciou pausado, sem workers ou
chamadas ao modelo. Isso testa a preservação da autoridade explicitamente
selecionada, não sua descoberta automática nem migração/restore de produção.
O recibo mantém `production_restore_qualified=false` e
`provider_counter_restore_qualified=false`. A cópia antiga jamais foi ativada.
