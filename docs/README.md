# Documentação da Fabriquinha

Referência revisada em **23 de outubro de 2026**. A plataforma é experimental;
autonomia completa ainda não foi qualificada. Os documentos públicos descrevem
contratos, limites e resultados agregados. Credenciais, transcrições, bancos,
snapshots e recibos operacionais completos permanecem privados.

## Por onde começar

| Documento | Quando consultar |
|---|---|
| [STATUS](STATUS.md) | Estado datado, estimativas de prontidão, bloqueio atual e próximos marcos |
| [ARCHITECTURE](ARCHITECTURE.md) | Componentes, diagrama do fluxo instalado e fronteiras de autoridade |
| [VALIDATION](VALIDATION.md) | O que foi testado, o que foi instalado e o que falta comprovar nativamente |
| [ROADMAP](ROADMAP.md) | Critérios objetivos para declarar entrega autônoma e reutilização |
| [SETUP](SETUP.md) | Instalação experimental, consulta segura, limites e organização Docker |
| [QA-PROTOCOL-RECOVERY](QA-PROTOCOL-RECOVERY.md) | Recuperação vinculada a evidências; texto técnico em inglês |
| [PATCH-RECEIPTS](PATCH-RECEIPTS.md) | Alcance dos recibos de edição; não concedem escrita ao revisor |

O [README principal](../README.md) apresenta o projeto. O contrato normativo de
qualidade está em [quality-lifecycle-v2](../team-delivery-kit/contracts/quality-lifecycle-v2.md).
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

Na referência consultada, controlador `20261023.33` e worker `20261023.9`
preservam resultados completos de leitura na revisão imutável. A revisão
nativa mais recente comprovou **71/71 arquivos**, mas terminou em
`technical_blocked`: o parecer não satisfez o contrato. Uma tentativa de
`request_changes` sem achados concretos exigia etapas posteriores antes de
aprovar os testes, criando uma dependência circular.

O próximo trabalho é tornar inequívocos o contrato da fase e o diagnóstico do
parecer, qualificar a mudança e obter outra decisão independente. Não é
fabricar aprovação a partir da leitura completa. Ainda faltam congelamento,
Green, controles negativos e a cadeia v2 de revisão da entrega até homologação.
Os bloqueios anteriores permanecem preservados. Temporal não é motor do
runtime instalado. Consulte [STATUS](STATUS.md) antes de qualquer retomada;
esta atualização documental não inicia testes ou libera manutenção.

## Política de atualização

Alterações de arquitetura devem atualizar o mapa e os diagramas; novas provas
devem distinguir fixture, execução nativa e instalação. Estimativas percentuais
são julgamentos de engenharia, não medições de autonomia. Consultas de estado
não autorizam liberar manutenção, consumir chamadas ou dispensar gates. A
disponibilidade da interface não comprova atividade dos agentes.
