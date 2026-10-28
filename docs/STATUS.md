# Status do projeto — 28 de outubro de 2026

**S4 técnico qualificado; S5 homologado com assistência; primeiro incremento S6
integrado e validado. O objetivo geral continua aberto.** A execução usa Hermes
SDK + Kanban nativos e operações determinísticas. Multica e Temporal não
participam desse caminho. A distribuição pública e a retomada do Truco completo
ainda não estão qualificadas.

## Estado atual do S6

**Desenvolvimento retomado com plano aprovado; despacho em manutenção.** Pausa persistente, nenhum worker/claim
pendente; supervisor descarregado, relay parado e política de provedor desabilitada.
A [auditoria de 28/10](EXECUTION-REVIEW-2026-10-28.md) apresenta percentuais,
causas dos bloqueios e o plano posteriormente aprovado pelo proprietário. O
[ADR 0007](ADR-0007-EVIDENCE-BASED-SUCCESSION.md) registra a implementação offline
e as qualificações delimitadas; o runtime instalado ainda não foi alterado.

O primeiro incremento do lobby passou por revisão independente, PR
[codifydeep/descartavel#13](https://github.com/codifydeep/descartavel/pull/13),
CI local obrigatória, implantação, rollback/restauração e QA de navegador.
Commit integrado: `2d2b7fb3b987748713e6f691d9c10fde9afd4ad2`.
O recibo conserva `delivery_approval=false`: comprova o incremento, não a release.

O segundo incremento está bloqueado na revisão dos testes. Depois de corrigir
uma fixture que buscava uma sala sem criá-la, a execução 69 produziu novo Red:
16 casos, sete falhas comportamentais, nenhum erro de execução ou skip.
Ainda não existe aprovação independente dessa revisão nem Green correspondente.
O card de testes está em triagem; implementação e integração sucessoras não começaram.

O CTO manteve hold pela suposta incompatibilidade entre HTTP 409 e console vazio.
A [prova isolada de clientes HTTP](S6-HTTP-CLIENT-DIAGNOSIS.md) demonstra que
409 recebido pelo Python não gera erro no navegador; um fetch do próprio navegador
recebendo 409 gera. Isso invalida a equivalência presumida, mas não aprova produto,
nem resolve por si só corrida entre clientes ou o lifecycle de saída da triagem.

Fonte instalada: `8d6bbd92`. A orientação adicional publicada em `fc202f3a` ainda
não foi instalada. `delivery_validate`, revisão aditiva de fixture e separação
de contexto diagnóstico foram implementados e receberam provas delimitadas.
A auditoria de 28/10 foi somente leitura. Após aprovação do plano, a suíte
offline passou com 458 testes. Provas nativas programadas cobrem a sucessora,
dependências, interrupções, solicitação de mudanças e nova revisão. Falta
qualificar a obtenção de evidência nova e a ativação da proposta pelos agentes,
além da recuperação real do S6; o runtime continua inalterado.

Consumo confirmado antes da pausa: **7.247/8.500 chamadas**, restando 1.253.
Claude Haiku, saída máxima de 16.384 tokens, contexto 131.072 e nenhum fallback.
A leitura do ledger parado conferiu a janela S6: 296 chamadas atribuídas,
US$ 1,2739285 reportados pelo provedor. Não é custo histórico total nem inclui
o assistente operador. Nenhum gate, contador ou evidência anterior foi dispensado.

Prontidão estimada para autonomia no escopo Python/HTTP atual: **cerca de 60%**,
com método e limites na auditoria. Não é probabilidade de sucesso ou fração do
esforço restante. A qualificação do Truco completo continua fora desse indicador.

## O que ainda falta

- Segundo incremento: Green com regressões, controles negativos, revisão,
  PR/CI, implantação, rollback e QA no mesmo commit; depois, aceite técnico S6.
- Canal real: intake, pergunta/resposta do CEO e entrega, com autenticação,
  vínculo de revisão e deduplicação. Nesta instalação, a entrada ainda é CLI e
  a rota de notificações Telegram não está configurada.
- Recuperação da instalação e upgrade/rollback operacional em isolamento;
  rollback do produto não substitui essa prova.
- Reprodução pública documentada e qualificação de entrega sem intervenções
  técnicas do operador. O S6 atual teve reparos no controlador e não será
  reclassificado como autônomo desde o briefing.

Ver [plano S6](S6-PORTABILITY-PLAN.md),
[histórico de recuperação](S6-CONTROL-SUBMISSION-RECOVERY.md) e
[auditoria aprovada](EXECUTION-REVIEW-2026-10-27.md).

## Evidências históricas de preparação

Os registros abaixo descrevem momentos anteriores; cotas, pausas e fontes ali
mencionadas não substituem o estado atual acima.

**Correção R1 validada:** 396 testes do núcleo; sete jobs reais de navegador;
dois incrementos dependentes pelo Hermes nativo com autores/revisores e GitHub
programados. A mesma aceitação congelada rodou na prévia e no deploy, preservando
regressão. Uma falha encontrada no ensaio agora impede congelar Red quando os
testes de navegador não chegaram a executar. Zero chamadas pagas. Isso não
qualifica agentes reais nem conclui S6. R2 passou nas provas operacionais locais:
bootstrap Compose com credencial fictícia, recusa de sobrescrita, leitura pelo
UID do relay, clone limpo e supervisão launchd com pausa preservada após crash.
O descarregamento é observado até desaparecer; não se repete bootout por atraso.
A política econômica foi conferida no S6 sem mudar contador ou teto. O bundle
novo já foi instalado na raiz S6 existente a partir da fonte publicada
`eaf52e21`, com recibo de upgrade, backup mínimo, board/brief preservados,
provedor desabilitado e despacho parado. A fonte operacional `e3e443c6` mantém
o bundle e acrescenta os comandos públicos de R2. O relay foi recriado desabilitado
nessa fonte em 6.953/7.064, sem hold. Após admissão verde e inspeção sem recursos
obsoletos elegíveis, o supervisor foi carregado, a política habilitada e o despacho
retomado. A primeira chamada do planejamento levou o contador a 6.954/7.064.
Iniciar scripts privados antigos não é o procedimento de retomada. A conclusão
S6 e canal/restore R4 continuam pendentes. As intervenções prévias ao despacho
permanecem registradas; S6 não é reclassificado como autônomo desde o briefing.

Na manutenção seguinte, foi identificada uma inconsistência: o plano permitia
o mesmo critério em dois pacotes, mas o manifesto recusava casos adicionais
desse critério no segundo arquivo. O reparo une cobertura de forma aditiva,
preserva arquivos congelados e recusa qualquer troca de bundle após evidência
de qualidade existente. O núcleo passou com 401 testes e a cadeia offline
concluiu os dois incrementos com critério transversal, PR/CI programados e
Docker/QA reais. Fonte instalada: `a89ffe37`. Retomada em 6.960/7.064, mantendo
plano, cards e histórico. Essa manutenção é uma intervenção adicional registrada,
não uma entrega autônoma de produto nem nova execução que apague o histórico.

## Resultado mais recente

O [S5](HERMES-S5-QUALIFICATION.md) entregou dois pacotes dependentes na mesma
aplicação: Reset e Undo. Os PRs [60](https://github.com/codifydeep/descartavel2/pull/60)
e [61](https://github.com/codifydeep/descartavel2/pull/61) foram integrados na
branch de release. O commit final é `9af291f509416e085958e281fed40c267fc3e750`.
A main do produto permaneceu intacta.

A auditoria conferiu:

- 18 testes na integração de Reset e 29 na de Undo, com os anteriores intactos.
- Red, congelamento independente, Green e controles negativos por entrega.
- Revisão independente, CI local no SHA do PR e do merge, imagem e commit exatos.
- Candidate/rollback/restore, QA dos oito critérios e serviço saudável.
- Memória da decisão S4 usada por Produto, sem herdar a aprovação antiga.
- Recuperação real e liberação automática da dependência após QA de Reset.
- Nenhum worker, claim, sandbox não retirado ou efeito pendente no encerramento.

O S5 registra **sete intervenções de manutenção**. Não é uma release autônoma
limpa. Depois da última instalação, a equipe reavaliou o impedimento e concluiu
o trabalho restante sem edição manual do produto. A exportação executada,
`e7349bb6`, manteve seus 27 arquivos inalterados e o bundle dos validadores fixado.

O [reparo de continuidade e memória](S5-DEPLOYMENT-CONTINUITY.md) preservou o
deployment anterior e corrigiu a seleção do rollback. O diagnóstico passou a
receber fatos atuais e histórico referenciado, em vez de instruções livres do
veredito anterior. O Lead executou um SPIKE e decidiu a retomada; o controlador
aplicou essa decisão. A instalação não desbloqueou o card diretamente.

## Consumo e operação

O S5 encerrou em **6.951/7.000**, com 49 chamadas restantes. Para S6, o proprietário
autorizou elevar o teto específico para **7.064**, sem reset do contador.
As duas chamadas de Produto em S6 levaram o contador a **6.953/7.064**,
restando 111; custo reportado dessas duas chamadas: **US$ 0,0046951**.
Na janela
após S4 houve 140 chamadas: 125 atribuídas por recibo a S5 e 15 sem vínculo
comprovado. O custo total reportado nessa janela foi **US$ 0,4845305**, incluindo
US$ 0,0633779 dessas chamadas sem atribuição. Não houve reset, desconto ou
atribuição por horário. A origem delas permanece não comprovada.

`runtime costs` consulta metadados sem inferência; polling e status não consomem
chamadas ao modelo. Telegram real ainda não está configurado nesta fronteira:
a fila de outbox não comprova recebimento de uma entrega pelo CEO.

A suíte do controlador passou em **386 testes**, também sem `site-packages`,
após o preparo de fonte/operação e a admissão dos perfis de S6. A execução S5 manteve a fonte anterior congelada. As provas programadas com
SDK/Docker qualificam mecanismos delimitados; não substituem julgamento real
nem medem a autonomia por porcentagem de testes verdes.

## Fronteiras de qualificação

| Marco | Evidência | Limite ou pendência |
|---|---|---|
| S0/S1 | Integração Hermes/Kanban, sem patches upstream | Não constitui entrega de produto |
| S2/S3 | TDD, revisão, operações e recuperação em isolamento | Não é julgamento real universal |
| P1/P3 | PRs 57/58 homologados com assistência | História preservada; não reclassificada |
| P2 | Bundle fixado e custo reportado contabilizado | Atribuição auxiliar integral ainda não garantida |
| P4/S4 | PR 59 sem intervenção técnica após o aceite | Stack Python/HTTP e brief reutilizado por autorização |
| P5/S5 | Segunda homologação, memória e recuperação reais | Sete intervenções; ainda não é um ciclo inteiro limpo |
| P6/S6 | Nova instalação pública, GitHub vinculado, bootstrap autorizado e duas chamadas atribuídas | Brief aprovado e execução pausada; QA entre sessões, canais, recuperação em execução e entrega em outro repo pendentes |
| P7/S7 | Não iniciado | Retomar Truco após qualificação da plataforma |

O [S4 original](HERMES-S4-QUALIFICATION.md) permanece como prova independente:
31 chamadas, US$ 0,074938 reportados e nenhuma intervenção técnica após o aceite.
As provas de regressão conhecida são separadas e documentadas nos
[contratos S5](S5-CONTRACT-QUALIFICATION.md); não convertem resultados antigos.

## Próximo trabalho

O [preparo de fonte S6](S6-PORTABILITY-PLAN.md) passou em clone Git local novo,
com início pausado, lock exclusivo, reinício e recusa de alteração do export.
Nessa prova não houve modelo nem jobs Docker. Em uma prova separada, a nova
receita pública do navegador passou em quatro jobs TDD e um probe QA real no UID
10000, em Linux ARM64. A homologação e as imagens instaladas foram preservadas.
O preparo público validou nove perfis e o SDK recusou last-known-good como
configuração atual válida. Um perfil divergente não impediu outro de ser admitido
no Kanban. O contrato também atravessou oito atividades SDK reais com respostas
locais, TDD e pausa/reinício. A instalação limpa agora usa clone público novo,
upstream sem patches, ambiente SDK novo e board/sessões novos. A entrega completa
por essa entrada continua em qualificação.

O preparo limpo revelou que o login GitHub do shell não era a identidade do
perfil nativo. O vínculo explícito do diretório GitHub do controlador foi
qualificado em DevOps e seus revisores QA/CTO, sem copiar tokens para perfis ou
contêineres. Um perfil não vinculado continuou sem herdar a identidade ambiente.
Os nove perfis permaneceram válidos; a instalação ficou pausada, sem cards ou
chamadas ao modelo. O `doctor` agora informa ausência ou divergência desse
vínculo. Isso qualifica autenticação para consultas, não PR/merge ou entrega
autônoma no novo repositório.

A base descartável aprovada foi publicada somente em uma nova branch de
`codifydeep/descartavel`, com CI local obrigatória. Main e sua proteção foram
conferidas intactas. A ativação conjunta do novo SDK e relay preservou volumes,
chave, medidor e homologação anterior; o serviço antigo ficou parado para
rollback. O backup foi extraído em isolamento, passou na integridade SQLite e
na leitura nativa dos cards e da pausa. Nenhum serviço foi iniciado nessa cópia;
isso não qualifica ainda recuperação de trabalho em andamento.

Produto já apresentou e corrigiu o brief da fatia de lobby para dois navegadores.
Uma exceção vaga de testes foi devolvida por revisão do operador antes do aceite
e corrigida pelo próprio Produto. Essa intervenção fica registrada. A auditoria
posterior constatou que a correção ficou excessivamente restritiva e conflita
com a autoridade técnica do ADR 0004; a harmonização está proposta, não aplicada.
Nenhum brief ou código de produto foi editado manualmente. O CEO aprovou o escopo;
não há entrega de produto S6 aprovada nem alegação de autonomia completa.

O [reparo de atribuição auxiliar](ADR-0005-VALIDATION-AND-ACCOUNTING.md) passou
no compressor real/relay com respostas simuladas e na recuperação nativa, sem
chamadas pagas. A ativação conjunta já reconhece `path-v1`; as primeiras chamadas
reais de Produto no S6 foram atribuídas às execuções e tiveram custos reportados.
Isso não reatribui as 15 chamadas históricas sem origem comprovada nem comprova
compressão real neste ciclo. Continuar a qualificação da instalação pública em
outro repositório, com status, pausa/retomada, upgrade/rollback, canais e
propriedade dos recursos. O ciclo usa fonte congelada, objetivo próprio e limite
autorizado. Não repetir outra saudação genérica nem
resetar o board para ocultar falhas.

O [plano S6](S6-PORTABILITY-PLAN.md), o [roadmap](ROADMAP.md) e o [resultado S5](HERMES-S5-QUALIFICATION.md) orientam a
continuação. As auditorias e ADRs anteriores preservam decisões e limites; não
são ordens concorrentes de execução.

## Recuperação do vínculo do grafo — 27/10

A primeira retomada após o reparo aditivo foi recusada porque o grafo ainda
fixava o bundle anterior. Nenhuma nova chamada foi enviada nessa recusa.
A correção reutiliza o recibo de upgrade e versiona o grafo sem editar cards.
401 testes passaram; a prova nativa final completou dois incrementos, 11
atividades SDK e 19 requisições locais programadas, com regressão e QA reais
em Docker. Testou interrupções nas duas ordens de gravação, recusa de despacho
parcial, recuperação sem duplicação e preservação dos cards. Zero chamadas pagas.

As tentativas anteriores ficaram preservadas: uma classificação incorreta da
interrupção planejada, uma reserva de rede ainda ocupada e um limite de observação
que não incluía o cooldown nativo de cinco minutos. O prazo da prova foi ajustado;
timeouts dos workers e cooldown de produção não mudaram. O deployment descartável
final foi retirado após salvar evidências. Essa prova programada não é autonomia
do modelo. A instalação real registra a manutenção adicional e mantém o histórico.
