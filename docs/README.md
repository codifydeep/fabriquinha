# Documentação da Fabriquinha

Referência revisada em **24 de outubro de 2026**. A plataforma é experimental;
autonomia completa ainda não foi qualificada. Os documentos públicos descrevem
contratos, limites e resultados agregados. Credenciais, transcrições, bancos,
snapshots e recibos operacionais completos permanecem privados.

## Por onde começar

**Revisão estratégica de 24/10:** [análise e plano de simplificação](SIMPLIFICATION-REVIEW-2026-10-24.md).
Propõe Hermes + Kanban com uma camada pequena de entrega, condicionado à prova
de isolamento. Plano e mudanças de contrato foram aprovados;
[S0/S1 estão concluídos](HERMES-S1-QUALIFICATION.md) no escopo da prova sem modelo.
A [primeira fatia S2](HERMES-S2-QUALIFICATION.md) qualificou os mecanismos TDD
e timeout com fixtures, ainda sem autonomia, serviço contínuo ou publicação.
A [fatia S3](HERMES-S3-QUALIFICATION.md) passou também por build, Compose,
QA real em Chromium e rollback. GitHub e pareceres continuam simulados; não
comprova autonomia. O [ADR 0002](ADR-0002-LOCAL-WEB-AND-QA-NETWORKS.md) delimita
a publicação local do web e a rede interna do QA.
O [ADR 0001](ADR-0001-HERMES-FIRST.md) rege o caminho novo. A referência antiga
permanece pausada e não deve receber nova expansão como pré-requisito da simplificação.

| Documento | Quando consultar |
|---|---|
| [STATUS](STATUS.md) | Estado datado, estimativas de prontidão, bloqueio atual e próximos marcos |
| [ARCHITECTURE](ARCHITECTURE.md) | Componentes, diagrama do fluxo instalado e fronteiras de autoridade |
| [VALIDATION](VALIDATION.md) | O que foi testado, o que foi instalado e o que falta comprovar nativamente |
| [ROADMAP](ROADMAP.md) | Critérios objetivos para declarar entrega autônoma e reutilização |
| [SETUP](SETUP.md) | Instalação experimental, consulta segura, limites e organização Docker |
| [QA-PROTOCOL-RECOVERY](QA-PROTOCOL-RECOVERY.md) | Recuperação vinculada a evidências; texto técnico em inglês |
| [PATCH-RECEIPTS](PATCH-RECEIPTS.md) | Alcance dos recibos de edição; não concedem escrita ao revisor |

O [README principal](../README.md) apresenta o projeto. O contrato instalado na
referência antiga está em [quality-lifecycle-v2](../team-delivery-kit/contracts/quality-lifecycle-v2.md).
O caminho novo segue o ADR 0001 e o plano aprovado, sem gate universal de leitura
integral. Não combinar as regras contraditórias das duas linhagens.
As seções históricas dos documentos não são inventário vivo nem comandos para
ativar outra linhagem de execução.

## Como interpretar o estado

- **Em fonte:** existe implementação; não comprova instalação.
- **Qualificado offline ou com fixture:** controles determinísticos passaram;
  não equivale a decisão real do modelo nem entrega do produto.
- **Instalado:** o código foi aplicado na referência; não qualifica toda a cadeia.
- **Execução nativa concluída:** o turno terminou; o controlador ainda precisa
  aceitar evidências e parecer. `completed` pode coexistir com `technical_blocked`.
- **HOMOLOGADA:** único sucesso terminal da release, depois de revisão, PR/CI,
  deploy, QA e rollback verificáveis no mesmo commit.

Na referência consultada, controlador `20261023.36` e worker `20261023.11`
preservam resultados completos de leitura na revisão imutável. A revisão
nativa terminal anterior comprovou **71/71 arquivos**, mas terminou em
`technical_blocked`: o parecer não satisfez o contrato. Uma tentativa de
`request_changes` sem achados concretos exigia etapas posteriores antes de
aprovar os testes, criando uma dependência circular.

O contrato da fase e o diagnóstico específico foram corrigidos, qualificados
no Hermes real sem provedor e instalados com backup/restauração verificados.
O coordenador despachou outra revisão nativa: ela parou com 46/71 arquivos e
duas promessas em prosa de continuar depois. A continuação por leitura real
passou na qualificação seguinte e foi instalada, sem ampliar orçamento ou forçar
aprovação. A recuperação foi registrada e a manutenção liberada para o coordenador.
A revisão seguinte comprovou 71/71 arquivos, mas o primeiro parecer final foi
rejeitado; a continuação recebeu HTTP 402. A instância está selada e o proxy
parado após pausa por pagamento, sem aprovação fictícia. O controlador novo foi
instalado com execução desligada; o serviço host está desabilitado e descarregado.
A recuperação específica de pagamento passou por qualificação Linux isolada,
com oito consultas HTTP a uma fixture local e nenhuma chamada ao provedor real.
Uma consulta diagnóstica posterior confirmou crédito e limite disponíveis, sem
chamadas ao modelo ou alteração da pausa. A causa do 402, confirmação de
remediação, registro da recuperação e ativação separada permanecem pendentes.
A migração do pin foi concluída,
preservando fila e histórico, sem iniciar o serviço.
A última suíte offline executou 4.522 testes, com oito skips preexistentes e
nenhuma falha. A estimativa consolidada permanece em 70%; não é medição de autonomia.
Faltam congelamento, Green, controles negativos e a cadeia v2 de revisão da
entrega até homologação.
O executor fixo para reexecutar a suíte na revisão da entrega já passou em
canário Docker, com snapshots somente leitura e cinco controles negativos.
Ainda não está conectado à admissão e ao despacho nativos do revisor; o canário
não equivale a revisão independente aceita ou homologação.
As partes de admissão e vínculo do recibo já existem em fonte com testes de
fixtures, mas não estão instaladas. Worker, transporte, parecer e integração
do coordenador continuam pendentes; não habilitar manualmente a nova fase.
Os bloqueios anteriores permanecem preservados. Temporal não é motor do
runtime instalado. Consulte [STATUS](STATUS.md) antes de qualquer retomada;
esta atualização documental não inicia testes ou libera manutenção.

## Política de atualização

Alterações de arquitetura devem atualizar o mapa e os diagramas; novas provas
devem distinguir fixture, execução nativa e instalação. Estimativas percentuais
são julgamentos de engenharia, não medições de autonomia. Consultas de estado
não autorizam liberar manutenção, consumir chamadas ou dispensar gates. A
disponibilidade da interface não comprova atividade dos agentes.
