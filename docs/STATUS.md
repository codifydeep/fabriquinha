# Status do projeto — 26 de outubro de 2026

**Caminho atual:** Hermes + Kanban nativos e executor determinístico. Multica e
Temporal não participam do caminho novo; a instalação legada permanece pausada.

**Estado mais recente:** o [PR 56](https://github.com/codifydeep/descartavel2/pull/56)
foi integrado e implantado, com CI e rollback/restauração. QA recusou o texto
visível, diferente do contrato congelado. Não houve `HOMOLOGADA`. Dispatcher e
relay estão desligados; a implantação e todas as evidências permanecem preservadas.
Consumo final observado: **6.627/7.000 chamadas**.

A correção em fonte transmite o erro real do navegador ao diagnóstico e executa
o mesmo QA congelado em Green, revisão e CI. Passou em **285 testes do núcleo**
e em sete jobs reais Docker/Chromium: unidade verde com QA incompatível recusada;
correção apenas de código passou com testes/QA intactos. Zero chamadas pagas.
Essa prova não qualifica autonomia. O [plano de retrabalho](POST-QA-REWORK-2026-10-26.md)
detalha a próxima lacuna: corrigir a mesma release após QA, sem reset ou
repetição do brief. O histórico abaixo registra as fronteiras anteriores.

**R1/F1 e R2 limitado qualificados offline; S4 real ainda incompleto.**
O proprietário aprovou o refinamento F1, implementado e validado com
Chromium/Docker. As provas R1/R2 usaram zero chamadas pagas. O novo S4 usa
Claude Haiku sob cota específica autorizada, com relay isolado e perfis limpos.
Uma tentativa real anterior chegou ao Green, mas terminou em triagem antes
da revisão da entrega. O CTO manteve um bloqueio explícito; relay e dispatcher
foram desligados após drenagem. O feedback dos controles e o limite de exploração
foram corrigidos e qualificados offline. Outra fronteira limpa teve brief e
plano aprovados, mas o QA sofreu duas interrupções por saída acima da política
e ficou em triagem do CTO. O dispatcher e o relay estão desligados após drenagem.
Nenhuma entrega foi aprovada por causa dessas interrupções.

O proprietário autorizou saída de 16.384 tokens, mantendo Haiku, 7.000 chamadas
e nenhum fallback. Uma geração única com contexto nativo preservado completou
duas chamadas de ferramenta válidas usando 8.735 tokens; nenhuma ferramenta foi
executada. O contador foi preservado em 6.484/7.000 antes do novo ensaio.

O ensaio seguinte completou Red, revisão/freeze, Green de dez testes, correção
autônoma da cobertura dos controles e revisão independente da entrega. O
[PR #55](https://github.com/codifydeep/descartavel2/pull/55) foi integrado com CI
local no SHA exato. **Não houve homologação:** o Docker esgotou suas sub-redes ao
criar as redes do deploy. A recuperação executou um SPIKE verde e manteve o
efeito incerto bloqueado, sem repetir a mutação ou aprovar a release. O ensaio
foi pausado com evidências preservadas; consumo encerrado em 6.522/7.000.

A correção reserva as duas redes antes do despacho pago e faz o deploy real
reutilizá-las explicitamente. Redes vazias de relays encerrados foram retiradas
com metadados arquivados; volumes, snapshots e outros projetos foram preservados.
Outro ensaio deverá comprovar a entrega completa após essas pré-condições.

A tentativa com redes reservadas passou pela revisão e correção do plano, mas
QA encerrou sem handoff. O SPIKE seguinte encontrou um erro de teste além das
assertions esperadas do Red. O diagnóstico rejeitava esse relatório negativo e
o Lead manteve o bloqueio; nenhuma implementação ou entrega foi aprovada. Foi
preservada e encerrada em 6.553/7.000 chamadas. A observação diagnóstica foi
corrigida sem relaxar os gates de entrega: 278 testes do núcleo verdes e prova
SDK/Docker de nove atividades/31 requisições locais até TDD revisado. Falta
revalidar a equipe real e completar homologação.

Outra tentativa concluiu Red/freeze e Green de nove testes, mas o autor parou
após recusas genéricas dos controles. Lead executou SPIKE e retomou a fase; a
conversa herdada encerrou novamente em texto, e o CTO preservou a triagem.
Consumo encerrado em 6.595/7.000, sem PR ou homologação nessa fronteira. A revisão
dos registros encontrou também subprocessos exploratórios sobrevivendo ao
timeout do cliente Docker, todos aposentados com o sandbox ao final da atividade.

O conjunto posterior corrige contexto após diagnóstico, deadline interno dos
descendentes, feedback concreto dos jobs recusados e a primeira abertura WAL.
Passou em 281 testes do núcleo, prova SDK/Chromium de nove atividades/32 chamadas
locais e revalidação financeira de onze atividades/19 chamadas locais. Zero
OpenRouter nessas provas. A nova fronteira real continua necessária; nenhum
bloqueio anterior foi zerado nem convertido em aprovação.

A [revisão da execução](EXECUTION-REVIEW-2026-10-25.md) é a referência atual para
achados e próximos passos. O [plano de 24/10](SIMPLIFICATION-REVIEW-2026-10-24.md)
continua sendo a estratégia aprovada. O [ADR 0003](ADR-0003-BEHAVIOR-CONTROL-TARGETS.md)
registra o aceite e os limites do contrato F1; recibos antigos permanecem históricos.

## Evolução comprovada

| Etapa | Evidência | Pendência |
|---|---|---|
| S0/S1 | Referência e integração Hermes/Kanban qualificados, upstream sem patches | Não constitui entrega de produto |
| S2 | Contrato 2 deriva alvos do Red e riscos independentes; prova Chromium preserva teste auxiliar | Julgamento semântico real e entrega S4 ainda necessários |
| S3 | Cadeia revalidada no contrato 2: dois incrementos, 11 atividades SDK, 17 respostas locais, Git/deploy/QA/rollback | PR e integração de feature por agentes reais; GitHub/CI ainda simulados nesta prova |
| S4 | Red/freeze, Green, controles, revisão, PR/CI/merge e deploy/rollback reais | QA comportamental recusado; retrabalho da mesma release e primeira homologação autônoma pendentes |
| S5 | Mecanismos parciais | Segunda versão, regressão, memória entre perfis e recuperação |
| S6 | Preparação parcial | Instalação limpa em outro repo e troca do caminho ativo |
| S7 | Não iniciado | Retomada do Truco após qualificação |

Na tentativa real anterior, QA recebeu mudanças, corrigiu e obteve aprovação
independente dos testes. A pausa humana interrompeu a implementação de forma
controlada. **Essa pausa não é uma falha do ensaio.** A alteração do contrato
exigiu nova fronteira; suas provas não foram importadas para a nova tentativa.
Até agora, nenhuma release S4 foi homologada autonomamente.

As cinco fronteiras identificadas pela auditoria não eram cinco execuções
completas: quatro não qualificaram entrega e a última ficou incompleta e pausada.
As fronteiras posteriores a R2 também não completaram a entrega. A aprovação de brief reutilizado comprova continuidade do
aceite, não uma nova descoberta autônoma de produto.

## Impedimentos encontrados na revisão

1. **Qualidade — corrigida em fonte:** o contrato 2 exige os alvos derivados do
   Red e riscos adicionais justificados pelo revisor. O teste auxiliar continua
   na suíte completa. Recibos históricos não são convertidos; o S4 antigo não
   pode ser retomado como se tivesse produzido provas desse contrato.
2. **Recuperação — R2 qualificado offline:** planejamento e integração agora
   despacham diagnóstico técnico com snapshot, experimento e orientação completos.
   A revisão retoma na mesma fase. A triagem nativa despacha o CTO, mas permanece
   bloqueada quando não há operação segura; o contador nativo não é zerado.
   Isso não equivale a recuperação universal nem a julgamento do modelo real.
3. **Autoridade:** falta caminho versionado para corrigir contrato de testes
   após freeze, sem alteração da entrega antiga e sem intervenção do operador.
4. **Contexto — parcial:** achados completos e proposta anterior do plano agora
   chegam ao novo worker, qualificados em nove atividades SDK/11 respostas locais.
   Memória arquitetural entre versões permanece em S5.
5. **Distribuição:** imagens locais históricas e preparação parcialmente manual
   impedem declarar o kit reproduzível por terceiros.

A outbox está implementada, mas o transporte real não está configurado na
instalação auditada. Notificações em fila não comprovam visibilidade no Telegram.

O núcleo auditado em `98e09069` tinha 19 módulos funcionais mais `__init__`,
5.060 linhas e 233 testes verdes, sem cobrir a contradição. Os testes novos
exercitam alvos, risco adicional, imutabilidade, skip, inventário e legado.
Os **270 testes do núcleo passaram**. Provas locais não equivalem a autonomia,
SLA ou portabilidade.

A revalidação integrada inicialmente encontrou esgotamento dos pools de rede
Docker. A falha foi preservada. Dois relays de ensaios antigos e suas redes
vazias foram retirados com propriedade/leases conferidos e logs arquivados;
volumes e instalação S4 atual foram preservados. A prova seguinte passou em
grupo isolado e retirou automaticamente seu deploy e redes ao terminar.

R2 percorreu dois incrementos dependentes com 15 atividades SDK e 24 respostas
locais: recuperou revisão do plano e falha de integração por Lead → CTO,
concluiu deploy/QA/rollback e retirou os recursos da prova. Outra prova manteve
uma triagem sob responsabilidade do CTO após reinício, recusando retomada
indevida e sem novas chamadas. Ambas usaram zero chamadas pagas; GitHub/CI
foram simulados. Uma tentativa anterior falhou por orientação de DevOps vazando
para a fase QA; foi preservada e o isolamento de fases foi corrigido antes da
prova aprovada. Veja [recuperação](HERMES-RECOVERY-QUALIFICATION.md).

As tentativas reais revelaram truncamento seguido de aumento indevido de saída
pelo SDK, caminhos do host no contexto do contêiner e feedback insuficiente dos
controles. O relay recusou corretamente saída acima da política. O contexto foi
corrigido para `/workspace`, com código de falha SDK limitado, sem resposta bruta.
Na tentativa seguinte o Lead recuperou o QA: Red, mudanças, correção e freeze
independentes ocorreram sem intervenção técnica externa. O incidente só resolveu
com freeze válido. A implementação passou nos dez testes, mas os controles
propostos não cobriram todos os alvos; um lote exploratório longo terminou sem
handoff. A triagem acionou o CTO e preservou o bloqueio, sem aprovação fictícia.

O gate agora informa os casos cobertos e ausentes, preservando todos os alvos e a
suíte completa. Schema e handler limitam exploração terminal a 120 segundos;
validação fixa continua com seu orçamento próprio. A prova de nove atividades
e 29 respostas locais verificou rejeição antes de execução, propagação do HTTP
422 e recuperação até as evidências TDD, sem chamadas pagas. Mudanças de fonte
exigem nova fronteira, sem importar evidências técnicas das tentativas bloqueadas.
O teto de chamadas só foi elevado por autorização explícita do proprietário;
modelo, limite de saída e ausência de fallback permanecem.

Uma melhoria offline posterior preserva recusas de cobertura dos controles em
recibo negativo, ligado à execução, Green, snapshot e freeze exatos. O diagnóstico
recebe todos os casos ausentes; se o código mudou, o contexto fica explicitamente
histórico e exige validação nova. Referências de outra execução/projeto/Green ou
evidência ausente são recusadas. A prova com decisões programadas concluiu 12
atividades e 38 respostas locais, incluindo saída do worker, reinício do supervisor,
Lead → CTO, correção pelo autor e revisão independente. Zero chamadas OpenRouter;
essa prova não transforma a release real bloqueada em entrega aprovada.

A fronteira posterior voltou a ser interrompida no QA por `output_budget_exceeds_policy`.
Dois canários sintéticos isolados (padrão e esforço baixo) retornaram argumentos
completos com 1813 e 1747 tokens de saída, ambos com zero tokens de raciocínio
reportados. Esse contexto curto não reproduziu a falha do SDK; não justifica
atribuir os cortes ao raciocínio nem mudar sua configuração.

Foi preparada a opção explícita de saída 16384, mantendo o limite de chamadas
7000 e nenhum fallback. Passou offline com 11 atividades SDK e 19 requisições
locais, incluindo pausa financeira e retomada; pedidos 32768 continuam recusados
sem reserva. Após o aceite explícito, uma geração com o contexto nativo
preservado disponível terminou completa com 8.735 tokens de saída. Esse contexto
é de uma tentativa anterior: a mais recente não preservou um dump equivalente.
Nenhuma ferramenta foi executada. O resultado permite outra tentativa S4;
recibos antigos e a resposta diagnóstica não contam como evidência de entrega.

## Próxima sequência

O [roadmap vigente](ROADMAP.md) detalha R0–R5:

- F1 aprovado, corrigido e revalidado fisicamente e na cadeia integrada offline.
- R2 limitado e correção de contexto revalidados offline, inclusive HTTP 422
  através do SDK real; feedback dos controles e exploração limitada qualificados.
- Saída maior autorizada e geração nativa completa; orçamento preservado.
- Executar uma tentativa S4 completa, com a equipe conduzindo os handoffs.
- Provar S5 e S6 antes de liberar S7.

Não reiniciar diretamente o ensaio com aprovações do contrato antigo. Não iniciar outra
migração, trocar o modelo ou ampliar consumo por conta desta análise.

## Como interpretar progresso

Os percentuais antigos eram estimativas subjetivas de outra arquitetura e foram
retirados deste status. Permanecem no histórico Git; não são uma série comparável
nem sinal de regressão medida. A avaliação passa a distinguir marcos comprovados,
tentativas assistidas, pausas e requisitos ainda sem evidência.

O único sucesso terminal continua sendo `HOMOLOGADA`, com brief coberto,
revisão, PR/CI, commit/imagem implantados, QA, rollback e URL verificáveis.
