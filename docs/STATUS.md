# Status do projeto — 27 de outubro de 2026

**S4 técnico qualificado; S5 homologado com assistência. O objetivo geral continua aberto.**
A execução usa Hermes SDK + Kanban nativos e operações determinísticas.
Multica e Temporal não participam desse caminho. A distribuição pública e a
retomada do Truco ainda não estão qualificadas.

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

O contador encerrou em **6.951/7.000**, com 49 chamadas restantes. Na janela
após S4 houve 140 chamadas: 125 atribuídas por recibo a S5 e 15 sem vínculo
comprovado. O custo total reportado nessa janela foi **US$ 0,4845305**, incluindo
US$ 0,0633779 dessas chamadas sem atribuição. Não houve reset, desconto ou
atribuição por horário. A origem delas permanece não comprovada.

`runtime costs` consulta metadados sem inferência; polling e status não consomem
chamadas ao modelo. Telegram real ainda não está configurado nesta fronteira:
a fila de outbox não comprova recebimento de uma entrega pelo CEO.

A suíte do controlador passou em **371 testes**, também sem `site-packages`,
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
| P6/S6 | Fonte/operação, receita pública ARM64 e preflight de nove perfis passaram; oito atividades SDK com perfis gerenciados e transporte local | Ativação conjunta, redes/provisionamento, canais, upgrade/restauração e entrega em outro repo |
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
locais, TDD e pausa/reinício. Falta integrar esses passos na qualificação da
instalação limpa, sem copiar os bancos ou sessões anteriores.

O [reparo de atribuição auxiliar](ADR-0005-VALIDATION-AND-ACCOUNTING.md) passou
no compressor real/relay com respostas simuladas e na recuperação nativa, sem
chamadas pagas. Preservar as 15 chamadas sem origem comprovada e validar a
ativação coordenada do SDK/relay. Depois, qualificar a instalação pública de S6 em outro
repositório, com status, pausa/retomada, upgrade/rollback, canais e propriedade
dos recursos. O próximo ciclo pago precisa de fonte congelada, objetivo próprio
de qualificação e cota suficiente. Não repetir outra saudação genérica nem
resetar o board para ocultar falhas.

O [plano S6](S6-PORTABILITY-PLAN.md), o [roadmap](ROADMAP.md) e o [resultado S5](HERMES-S5-QUALIFICATION.md) orientam a
continuação. As auditorias e ADRs anteriores preservam decisões e limites; não
são ordens concorrentes de execução.
