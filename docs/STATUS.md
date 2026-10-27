# Status do projeto — 27 de outubro de 2026

**S4 técnico qualificado; S5 homologado com assistência. O objetivo geral continua aberto.**
A execução usa Hermes SDK + Kanban nativos e operações determinísticas.
Multica e Temporal não participam desse caminho. A distribuição pública e a
retomada do Truco ainda não estão qualificadas.

**Pausa operacional confirmada:** controlador e relay S6 parados, provedor
desabilitado e sem workers. Homologação anterior preservada. O brief S6 foi
aprovado pelo CEO; o aceite está guardado, ainda não aplicado ao intake.
A [auditoria de 27/10](EXECUTION-REVIEW-2026-10-27.md) recomenda corrigir a
capacidade de QA entre sessões e a divergência de autoridade técnica antes do
despacho. O proprietário aprovou os refinamentos e a retomada das correções;
o [ADR 0006](ADR-0006-SHARED-ACCEPTANCE.md) passou na qualificação offline. O
despacho S6 continua parado até concluir a preparação. Zero chamadas na auditoria.

**Correção R1 validada:** 396 testes do núcleo; sete jobs reais de navegador;
dois incrementos dependentes pelo Hermes nativo com autores/revisores e GitHub
programados. A mesma aceitação congelada rodou na prévia e no deploy, preservando
regressão. Uma falha encontrada no ensaio agora impede congelar Red quando os
testes de navegador não chegaram a executar. Zero chamadas pagas. Isso não
qualifica agentes reais nem conclui S6. R2 ainda exige provisionamento público
de credenciais/volumes e supervisão/parada econômica reproduzíveis. O bundle
novo já foi instalado na raiz S6 existente a partir da fonte publicada
`eaf52e21`, com recibo de upgrade, backup mínimo, board/brief preservados,
provedor desabilitado e despacho parado. O relay e o supervisor deverão usar
essa fonte na próxima ativação; iniciar scripts privados antigos não é o
procedimento de retomada.

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
