# S5 — Segunda homologação, com assistência preservada

## Resultado de 27/10/2026

A segunda versão chegou a `HOMOLOGADA` na mesma aplicação e board nativo Hermes.
O commit final é `9af291f509416e085958e281fed40c267fc3e750`, integrado pelo
[PR 61](https://github.com/codifydeep/descartavel2/pull/61). O pacote Reset veio do
[PR 60](https://github.com/codifydeep/descartavel2/pull/60), commit `454b845a`.
A main do produto permaneceu na referência anterior; as integrações usaram a
branch de release. O S4 original não foi apagado ou requalificado.

**A entrega é assistida:** houve sete intervenções de manutenção após o aceite
do brief. Não representa uma segunda release inteira sem assistência, nem prova
universal de autonomia. Depois da última instalação, a equipe retomou o incidente
e concluiu os dois pacotes pendentes sem intervenção adicional no produto.

| Pacote | Base integrada | Suíte completa | Controle negativo | Revisão |
|---|---|---|---|---|
| Reset | Homologação S4 | 18 testes | 7 jobs, 12 alvos exigidos | Testes e código revisados por perfil independente |
| Undo | Reset aprovado em QA | 29 testes | 7 jobs, 9 alvos exigidos | Testes e código revisados por perfil independente |

As quantidades de alvos são por pacote; não são contagens de alvos únicos entre
pacotes. Os testes anteriores e contratos QA ficaram intactos e foram reexecutados.
A autoria dos testes foi de `quality_security`, a implementação de `frontend`
e as revisões de `techlead`. GitHub usa uma conta; independência é lógica por
perfil/recibo, não separação criptográfica de credenciais ou modelos.

## Evidências conferidas

- Brief novo aprovado explicitamente; aprovações antigas não foram transplantadas.
- Produto citou a decisão homologada anterior, feita por outro perfil; o plano
  preservou a arquitetura relevante, sem herdar sua aprovação de negócio.
- Dois pacotes dependentes. Undo só iniciou depois de Reset passar por QA.
- Red, congelamento independente, Green e controles negativos ligados às entregas.
- PR, revisão, CI local no SHA do PR e do merge, build e imagem correspondentes.
- Candidate/rollback/restore e QA independente no commit implantado.
- Todos os oito critérios aprovados cobertos na QA final; QA anterior reexecutada.
- Serviço saudável e identidade HTTP coerente com o commit final.
- Zero workers, claims, sandboxes não retirados ou efeitos pendentes no encerramento.

A última execução usou a exportação da fonte `e7349bb6`; seus 27 arquivos
permaneceram inalterados. O bundle dos validadores permaneceu fixado. Os recibos,
manifestos, conversas e auditoria de instalação continuam privados, fora do Git.
A suíte do controlador passou em 344 testes; esse número não mede autonomia.

## Recuperação observada

O seletor de rollback foi corrigido para reconhecer a homologação anterior exata.
A guarda contra substituição de deployment divergente permaneceu ativa. A prova
isolada passou por duas releases antes da instalação do reparo.

O modelo ainda repetiu um hold histórico apesar de receber os artefatos corretos.
O repasse de memória foi então limitado a recibos e resultados observados, sem
injetar o antigo veredito livre como instrução atual. O texto antigo foi preservado.
Os fatos do serviço passaram a integrar o novo SPIKE.

O Lead executou o experimento e decidiu `resume`. O controlador aplicou a decisão
no card original, executou a integração e liberou Undo. O time corrigiu uma
solicitação de revisão dos testes e completou os controles negativos faltantes
sem edição manual do produto. A auditoria só considerou o incidente resolvido
após a evidência de entrega; a simples existência de um worker não bastou.

Detalhes e limites do mecanismo: [continuidade de implantação](S5-DEPLOYMENT-CONTINUITY.md).

## Consumo e limites

Na janela após o S4, o contador avançou de 6.811 para **6.951/7.000**:

- 140 chamadas contabilizadas, incluindo falhas e atividades auxiliares.
- 125 ligadas por recibo à execução S5: US$ 0,4211526 reportados.
- 15 sem vínculo comprovado de atividade: US$ 0,0633779 reportados.
- Total registrado nessa janela: **US$ 0,4845305**. Não é estimativa de preço.

A origem das 15 chamadas não foi inferida por horário ou texto. Elas não foram
apagadas, descontadas do contador ou consideradas gratuitas. A atribuição auxiliar
precisa ser corrigida e revalidada antes de declarar rastreamento completo.

Telegram real e entrega ao CEO pelo canal continuam pendentes; fila de outbox
não comprova recebimento. Instalação pública limpa, portabilidade, ciclo de
upgrade/rollback e um ciclo completo sem assistência na nova fronteira pertencem
a S6. O objetivo geral permanece aberto; não repetir outra saudação genérica para
esconder as lacunas de distribuição e operação.
