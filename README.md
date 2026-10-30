# Fabriquinha

Uma equipe de agentes para transformar um brief em software revisado, testado e
entregue em homologação, com GitHub e infraestrutura própria.

**Experimental. Primeiro ciclo técnico completo sem intervenção externa qualificado.**
O caminho em validação usa **Hermes + Kanban nativos**, com operações determinísticas para
qualidade, publicação e implantação. Multica e Temporal não são dependências
desse caminho. A instalação legada está preservada e pausada.

[Status atual](docs/STATUS.md) · [Próximos passos](docs/ROADMAP.md) ·
[Revisão crítica de 28/10/2026](docs/EXECUTION-REVIEW-2026-10-28.md) ·
[Documentação](docs/README.md)

**S6 homologado com assistência; P5 em validação.** Os dois incrementos do
lobby passaram por revisão, PR/CI, implantação, rollback e QA. O ciclo permanece
assistido pelas correções anteriores da automação. Canal Telegram instalado com
um único bot e comandos explícitos; saída confirmada, entrada humana ainda pendente.
A cópia sintética foi restaurada e reiniciada sob pausa; o backup real passou na
inspeção de dados. Recuperação operacional completa e duas entregas comparáveis
sem intervenção técnica continuam pendentes. Veja [evidências P5](docs/CHANNEL-AND-OPERATIONS-P5.md).
Os diagramas descrevem a arquitetura instalada, sem prometer autonomia geral.

## O que queremos construir

O proprietário informa o objetivo de uma versão e aprova seu brief. A equipe
planeja, escreve testes, implementa, revisa, integra e entrega uma URL de
homologação com evidências. Impasses técnicos pertencem ao Tech Lead e ao CTO;
decisões de negócio pertencem ao proprietário.

A release só termina com sucesso em `HOMOLOGADA`. Worker ativo, card concluído
ou testes do controlador passando não equivalem a uma release entregue. Uma
pausa humana ou dependência externa também não significa cancelamento.

## Arquitetura atual

```mermaid
flowchart LR
    DASH[Hermes dashboard: consulta local] --> K
    CEO[Proprietário: brief e decisões de negócio] --> TG[Telegram: comando explícito e identidade humana]
    TG --> IN[Intake: card e revisão exatos]
    IN --> K[Hermes Kanban]
    LS[launchd opcional: supervisão macOS] --> C[Controlador nativo: pausa e lock único]
    C --> K
    A[Admissão: imagens, disco e redes reservadas] --> K
    SRC[Commit Git: export fechado e hash verificado] --> W[Agentes via SDK Hermes]
    PC[Perfil: contrato e configuração efetiva] --> W
    K --> W
    W --> S[Sandbox por atividade e deadline interno]
    S --> E[Snapshot e recibos imutáveis]
    E --> V[Validação fixa em Docker]
    VB[Bundle imutável e mesma aceitação congelada] --> V
    VB --> D
    V --> K
    K --> G[PR e CI local no GitHub]
    GI[Conta GitHub do controlador: vínculo explícito por perfil] --> G
    G --> D[Compose local e QA]
    D --> H[Gate de homologação]
    H --> K
    H -.-> HM[Última decisão homologada: contexto histórico limitado]
    HM -.-> W
    K --> O[Outbox persistente e status]
    O --> TG
    W --> U[Relay: consumo por atividade]
    K --> R[Diagnóstico técnico Lead / CTO]
    V -.->|recusa vinculada ao diagnóstico| R
    R --> X[Experimento fixo e evidência]
    X -->|retomada segura na fase original| K
    X -->|sem operação segura| B[Bloqueio com responsável e próxima ação]
```

Kanban é o dono do ciclo de vida. O controlador executa operações fixas e verifica
artefatos; os agentes não recebem credenciais de infraestrutura nem socket Docker.
O journal de efeitos evita duplicar ações com confirmação incerta e não é um
segundo gerenciador de tarefas.

Diagnósticos podem observar relatórios com erros para orientar reparos; esses
relatórios continuam impedindo aprovação em todos os gates de entrega.

A [continuação após submissão incompleta](docs/S6-CONTROL-SUBMISSION-RECOVERY.md)
passou na qualificação offline com participantes programados. Ela reutiliza Lead, CTO e
Kanban, preserva a triagem histórica e exige novos gates para a entrega. Está instalada, mas ainda
não foi comprovada com agentes reais; não constitui recuperação
genérica de qualquer impedimento.

Uma orientação técnica aplicada abre contexto SDK novo, reconstituído pelos
artefatos e achados duráveis. O histórico anterior permanece arquivado. Pausas
financeiras mantêm a sessão e a fase; não são tratadas como uma falha técnica nova.

Entregas reais exigem as duas redes de homologação reservadas antes do despacho
pago. O deploy usa essas redes como externas; não aloca sub-redes implicitamente.
O preparo é explícito e não remove redes desconhecidas ou repete criações incertas.

O suporte atual é limitado a uma stack Python/HTTP local, containers Linux ARM64
na instalação de referência e uma release ativa por projeto. Não há instalador
completo qualificado para terceiros. A matriz de nove perfis permite especialistas
sob demanda; não exige nove passagens para toda atividade.

## Fluxo da equipe

```mermaid
flowchart TD
    B[Produto: brief aprovado pelo proprietário] --> P[Tech Lead: plano]
    P --> C[CTO: revisão técnica]
    C -->|mudanças| P
    C --> T[QA: Red novo ou regressão existente no SHA exato]
    T --> F[Revisão independente e freeze]
    F -->|mudanças| T
    F --> I[Desenvolvedor: suíte Green e QA congelado local]
    I --> N[Controles negativos e revisão da entrega]
    N -->|mudanças| I
    F -->|devoluções recorrentes| ER[CTO: SPIKE e orientação]
    N -->|devoluções recorrentes| ER
    ER -->|revisão de testes| F
    ER -->|revisão da entrega| N
    N --> PR[PR e CI no SHA exato]
    PR --> M[Integração: suíte e mesmo QA congelado]
    M --> D[DevOps: deploy e rollback]
    D --> Q[QA independente do ambiente]
    Q -->|aprovado| H[HOMOLOGADA com URL e evidências]
    Q -->|falha| X[Lead: classificar erro contra o brief]
    X --> R[Proposta corretiva e revisão independente]
    R -->|produto| T
    R -->|expectativa textual no contrato legado| RT[Correção restrita; Red histórico preservado]
    RT --> F
    R -->|teste Python congelado sem reparo qualificado| E
    R -->|infraestrutura ou escopo| E[Impedimento explícito com responsável]
```

O código conecta essas etapas; as provas determinísticas exercitam a cadeia.
O [reparo mínimo](docs/ADR-0004-SCOPED-REPAIR.md) limita-se ao último pacote
serializado e, para testes, à expectativa textual QA explicitamente autorizada.
Não é replanejamento geral nem permissão para remover cobertura.
O [contrato novo](docs/ADR-0006-SHARED-ACCEPTANCE.md) executa a mesma aceitação
Python/Playwright em prévia e deploy. Revisão de teste Python já congelado ainda
é impedimento técnico ao CTO, sem autorização implícita para editar a entrega.
O [PR 59](https://github.com/codifydeep/descartavel2/pull/59) completou a primeira
entrega técnica sem intervenção externa: nove testes, controles, revisão,
PR/CI, deploy, rollback e QA. O ensaio reutilizou explicitamente um brief já
aprovado; não comprova descoberta de requisitos novos. Veja o
[escopo da qualificação S4](docs/HERMES-S4-QUALIFICATION.md). Continuidade entre
versões, distribuição e canais de comunicação ainda exigem validação.

A [auditoria](docs/EXECUTION-REVIEW-2026-10-25.md) encontrou um gate de mutações
incompatível com um teste auxiliar congelado. O [contrato 2 aprovado](docs/ADR-0003-BEHAVIOR-CONTROL-TARGETS.md)
corrige essa exigência e passou em prova física de navegador. Caminhos de
recuperação, memória entre versões e portabilidade continuam incompletos.

## Qualidade e segurança

- Red real → revisão independente dos testes → freeze → Green → controles
  negativos → revisão da entrega → PR/CI → QA da implantação.
- Testes existentes e descoberta protegidos; nenhum skip ou aprovação textual
  substitui execução. Correções legítimas exigem outra revisão, nunca alteração
  silenciosa do snapshot.
- [Regressões conhecidas](docs/S5-CONTRACT-QUALIFICATION.md) usam o teste existente
  vermelho, revisão e freeze, produto corrigido e cabeça verde. A CI admite somente
  as falhas de base revisadas no SHA e inventário exatos.
- Instalações novas fixam os scripts de validação em snapshot imutável; edição
  do checkout não altera os jobs nem reinterpreta provas anteriores.
- Revisores leem entregas imutáveis. Validações executam comandos fixos em
  containers sem credenciais, sem socket e com rede restrita à fase.
- Aprovações vinculadas a autoria, execução e artefato; integração e QA conferem
  o commit e a imagem efetivamente implantados.
- Na stack com browser TDD e papéis de entrega, Green, revisão e CI executam
  também o QA congelado, pelo mesmo interpretador do pós-deploy. Texto esperado
  significa texto completo normalizado; uma suíte unitária verde não o substitui.
- Pausa persistente, limites explícitos de consumo, nenhuma troca automática
  de modelo ou ampliação automática de orçamento.
- Recuperação técnica já foi demonstrada em cenários delimitados. Não há
  garantia de recuperação de todo impasse ou ausência universal de starvation.

## Organização do código

```text
src/fabriquinha/       Caminho novo: runtime, Kanban, qualidade e entrega
tests/                Testes offline do núcleo
scripts/              Preparação parcial, qualificações e publicação segura
docs/                 Status, plano vigente, arquitetura e provas delimitadas
Dockerfile*           Receitas de imagem; veja limites de reprodução
team-delivery-kit/    Legado preservado e utilitário de agrupamento Docker
bootstrap/infra/      Histórico; não iniciar junto ao caminho novo
```

Os caminhos legados permanecem para recuperação e referências de builds.
Não são o ponto de partida de uma instalação nova. Histórico detalhado e versões
anteriores deste README continuam no Git; o README não é diário de operação.

## Começar sem gastar tokens

A suíte do núcleo foi verificada com Python 3.14, inclusive sem pacotes de
`site-packages`. Ela não precisa do SDK Hermes, Docker ou chave de modelo:

```bash
git clone https://github.com/codifydeep/fabriquinha.git
cd fabriquinha
python3.14 -m venv .venv
. .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -q
python scripts/check_publication.py
```

Isso testa o controlador, não inicia agentes e não instala a plataforma. As
qualificações com Hermes/Docker têm dependências próprias e procedimentos em
[SETUP](docs/SETUP.md). Não execute overrides de instalações históricas como
se fossem um instalador. Imagens locais por digest ainda não asseguram
reprodução a partir de um clone limpo. A [receita pública do navegador](docs/SETUP.md#imagens-públicas-da-stack-pythonhttp)
já passou em probes TDD/QA sobre Linux ARM64; o instalador completo continua em S6.

## Situação das validações

Em 28/10/2026, a suíte passou em 490 testes. As provas operacionais do Hermes
usam o SDK preparado em Python 3.14.10; as qualificações históricas mantêm seus
ambientes e limites próprios. A [entrada operacional de S6](docs/S6-PORTABILITY-PLAN.md)
passou em clone/board novos, sob pausa, com fonte verificada e lock exclusivo;
isso ainda não é uma instalação completa ou nova entrega de produto.
O preparo público também verificou nove perfis, recusa de configuração antiga
e admissão independente. O contrato passou em oito atividades SDK com respostas
locais, TDD e pausa/reinício, sem chamadas pagas. Modelo/orçamento ficam na política
do controlador; os perfis gerenciados seguem essa rota.
O reparo mínimo completou uma
homologação assistida. As provas S1–S3 e extensões qualificam fronteiras
específicas; decisões programadas não são julgamento de um agente real.

O [ADR 0005](docs/ADR-0005-VALIDATION-AND-ACCOUNTING.md) fixa os validadores das
instalações novas e contabiliza campos de custo/cache retornados pelo provedor,
sem estimar gasto ausente. Foi qualificado em treze jobs Docker/Chromium e nove
atividades SDK com respostas locais, sem chamadas pagas. O comando `runtime
costs` consulta o relay local autenticado e não libera pausas nem faz inferência.

O [S4](docs/HERMES-S4-QUALIFICATION.md) foi concluído sem correção externa do
controlador ou dos artefatos após o aceite do brief. Foram 31 chamadas e
US$ 0,074938 reportados. Os PRs 57/58 permanecem assistidos. O [S5](docs/HERMES-S5-QUALIFICATION.md) entregou Reset/Undo com 29 testes,
memória entre perfis e recuperação real, preservando sete intervenções externas.
Ainda faltam ciclo limpo nessa fronteira, atribuição auxiliar completa e uma
instalação reproduzível em outro repositório. O canal Telegram está instalado, mas sua interação humana completa ainda não foi qualificada.
Veja o [roadmap](docs/ROADMAP.md).

## Retirada de recursos de teste

Todo container novo deve aparecer em um grupo Compose no Docker Desktop.
Serviços, testes descartáveis e homologação têm grupos próprios por instância.

Antes e depois de um ciclo, inventarie apenas recursos com propriedade comprovada.
Confirme ausência de leases ativos, preserve logs e recuperação e remova por ID
exato. O preview `team-delivery-kit/cleanup_port2_history.py --tests-only` vale
somente para os helpers port2 qualificados, não para qualquer nome parecido.
A limpeza de imagens usa `cleanup_obsolete_images.py` e o hash do plano revisado.

Não usar prune global, force ou apagar volumes/snapshots como rotina. Preservar
deploy atual, referências de build, rollback e projetos alheios, incluindo
`toso-*` e `reforma`. Consulte [AGENTS.md](AGENTS.md).

## Contribuição e licença

Não publicar chaves, instalações privadas, bancos, conversas, snapshots ou
worktrees de produtos. Rodar `python scripts/check_publication.py` sobre o
conteúdo staged antes de publicar. Mudanças da automação e entregas de produtos
têm contratos de revisão distintos; nunca transportar uma dispensa entre eles.

Código próprio sob [MIT](LICENSE). Dependências mantêm suas licenças.

### Recuperação de revisão

```mermaid
flowchart LR
    B[Revisão bloqueada] --> D[Diagnóstico CTO em cópia descartável]
    D --> A[Admissão determinística com evidências]
    A --> R[Revisão independente da entrega original]
    R -->|Mudanças| I[Autor corrige e submete nova entrega]
    I --> R
    R -->|Aprovação vinculada à entrega| G[Próximos gates obrigatórios]
```

A admissão permite revisar; não aprova testes, código ou release. A proposta
intermediária de recuperação foi removida apenas desse caminho. A prova nativa
isolada valida transferência e recuperação de crash com decisões programadas;
a recuperação real com modelo e a homologação completa do S6 seguem pendentes.

### Recuperação técnica de testes

O contrato de reparo técnico preserva os testes anteriores e permite correções
restritas a casos autorizados pelo CTO, com novo congelamento independente e
controles negativos obrigatórios. A qualificação isolada inclui executor Docker
e recuperação de cards no Kanban; ainda não comprova entrega autônoma.
Veja [contrato e evidências](docs/TECHNICAL-TEST-REPAIR.md).

```mermaid
flowchart LR
    B[Implementação bloqueada] --> C[CTO: experimento e escopo exato]
    C --> A[Controlador: validar identidade e dependências]
    A --> T[Autor: nova revisão dos testes]
    T --> R[Revisor independente: novo congelamento]
    R --> I[Implementação: Green e controles negativos]
    I --> D[Revisão, PR, CI, deploy e QA]
```

A transição mantém o incidente e os snapshots antigos; um worker ativo ou um
novo congelamento não equivale a homologação.

Local board access and observation limits: [Local Hermes Kanban](docs/LOCAL-KANBAN.md).
