# Brief aprovado e planejamento independente

Data: 24/10/2026. Estado: **intake passou com Hermes/Kanban/SDK reais e respostas
HTTP locais programadas**. Não comprova julgamento de modelo, entrega de
produto, homologação ou migração.

## Caminho implementado

1. Operador registra objetivo original, versão e chave estável de requisição.
   O controlador cria uma âncora `RELEASE` e um card de Produto no Kanban nativo.
   Repetir a requisição não duplica cards; reutilizar a chave com outro objetivo
   é recusado. Uma segunda release exige encerramento qualificado da primeira.
2. Produto recebe objetivo e histórico de sua sessão. Pode pedir esclarecimento
   essencial de negócio/usuário ou propor brief com critérios identificados,
   exclusões, premissas e decisão de instrumentação.
3. Pergunta/proposta fica em recibo imutável. O card entra em **revisão humana
   nativa**, atribuído à identidade reservada `fabriquinha-ceo`, sem worker humano
   fictício. Não instalar perfil de modelo com esse nome. `Board` recusa revisão
   de brief por agente antes de chamar o modelo.
4. O operador consulta e responde pelo CLI local confiável: `answer` responde
   uma pergunta; `changes` devolve o brief; `approve` aprova aquele recibo.
   Respostas de outra revisão/card são recusadas. Isso não libera orçamento,
   ferramentas, merge, exceções de testes ou homologação.
5. Aprovação completa o brief e permite criar um único card do Tech Lead, com
   dependência nativa do brief. A reconciliação usa a aprovação persistida:
   reinício entre aprovação/criação não requer outra decisão nem duplica plano.
6. Lead propõe arquitetura e DAG de pacotes com donos, dependências e aceite.
   Exigem-se IDs únicos, grafo acíclico, donos na matriz e cobertura de **todos**
   os critérios aprovados, sem inventar critérios. A revisão independente ainda
   deve avaliar a semântica, não apenas a validade da estrutura.
7. Plano passa pela matriz — na prova, Lead → CTO. Revisor não pode substituir
   documento; mudanças retornam ao autor; aprovação vincula plano/run exatos.

Não há outra base de workflow. Cards, revisões, dependências e handoffs pertencem
ao Hermes; documentos são recibos privados do armazenamento já existente.

### Espera humana não é falha técnica

`block_task(needs_input)` a cada esclarecimento faria a terceira pergunta atingir
o breaker de infraestrutura. Foi escolhida revisão humana e
`reopen_review_task` nativos, sem zerar contadores, editar SQL ou criar scheduler.
Três esclarecimentos consecutivos e uma devolução do brief passaram. Uma resposta
só reabre o card correspondente.

Status expõe `business_input` com recibo/escopo; `show` apresenta o documento ao
operador. A outbox distingue espera de negócio e não a escala ao CTO como impasse
técnico. Telegram real ainda não ativado/qualificado.

### Ferramentas

`findings` contém apenas defeitos bloqueantes. Para `approve`, deve ser `[]`;
observações positivas ficam em `reason`. Para `changes`, é obrigatório pelo
menos um achado concreto. Schema e erro do handler agora expõem essa mesma
condição. O S4 encontrou uma tentativa de aprovação com elogios nessa lista;
o modelo repetiu o payload e encerrou em texto. Esse run permaneceu bloqueado,
sem parecer aprovado. A aprovação textual não foi aproveitada.

A repetição offline de 25/10 passou com nove atividades SDK e 11 respostas
locais através do relay neutro: o payload inválido foi recusado, a orientação
corretiva chegou ao modelo de fixture e a chamada seguinte aprovou formalmente
com lista vazia. Zero inferência paga. Isso qualifica feedback/protocolo,
não garante que um modelo real sempre se corrigirá. Falhas de protocolo nas
fases documentais ainda não têm o SPIKE de produto usado para testes/código.

Brief: `brief_question`/`brief_submit`. Plano: `plan_submit`. Revisão: `plan_review`.
Não existem ferramentas de terminal, arquivos, Docker, administração ou aprovação
de negócio nessas atividades. Usam o registro restrito de handlers e a barreira
de pausa existentes, sem backend de terminal nessas fases documentais.

## Configuração e comandos

Trecho complementar ao contrato completo, antes da instalação:

```json
{
  "coordination_roles": {"product": "produto", "lead": "techlead"},
  "reviewers": {"techlead": "cto"}
}
```

Havendo `technical_roles`, seu Lead deve ser o mesmo. Isso muda a identidade do
projeto: não editar uma instalação existente silenciosamente.

Arquivo privado de entrada, sem credenciais:

```json
{"request":"primeira-tentativa","label":"v0.1","objective":"Objetivo original do CEO"}
```

Na raiz dos fontes, com ambiente Hermes qualificado e caminhos explícitos:

```bash
PYTHONPATH=src /CAMINHO/VENV/bin/python -m fabriquinha.intake start \
  --root /INSTANCIA --upstream /HERMES/FIXADO --file /ENTRADA/PRIVADA.json
PYTHONPATH=src /CAMINHO/VENV/bin/python -m fabriquinha.intake show \
  --root /INSTANCIA --upstream /HERMES/FIXADO --task ID_DO_BRIEF
PYTHONPATH=src /CAMINHO/VENV/bin/python -m fabriquinha.intake respond \
  --root /INSTANCIA --upstream /HERMES/FIXADO --task ID_DO_BRIEF \
  --expect RECIBO_EXATO --decision approve --text 'Aprovo este escopo de negócio'
```

Esses comandos registram decisões: não iniciam serviço ou liberam consumo.
`show` contém informação privada do produto; não publicar a saída. O CLI é um
canal local confiável, não endpoint remoto autenticado/comando Telegram pronto.

## Evidências e limites

`scripts/qualify_hermes_intake.py` criou somente a entrada original, não cards de
implementação. O serviço gerou brief/plano. Respostas e decisões de CEO/CTO são
programadas explicitamente para testar o mecanismo.

A segunda prova, após acrescentar CLI, dependência e observabilidade, concluiu:

- Três perguntas, uma devolução do brief e aprovação da revisão exata.
- Cinco atividades de Produto, **uma sessão**, quatro retomadas.
- Recusa de resposta antiga, aprovação de pergunta como brief e proposta obsoleta.
- Reinício antes da aprovação; repetição sem outro plano; dependência brief →
  plano conferida no banco nativo.
- Plano parcial recusado; CTO pede mudanças no completo; mesmo Lead reapresenta;
  CTO aprova o recibo exato.
- Nove atividades SDK, dez respostas locais, zero jobs Docker/chamadas pagas.
  Instância encerrada/pausada sem workers, claims ou efeitos pendentes.

A primeira prova também passou, antes das ampliações; não prova os comandos ou
observabilidade posteriores. Recibos/sessões/transcrições ficam privados. A fila
de notificações foi preservada sem destino de envio configurado.

Uma terceira prova repetiu o fluxo com a mesma implementação e injetou uma
interrupção **depois do commit da aprovação e antes da criação do plano**. O
brief ficou `done` com recibo válido, sem plano criado. Um novo processo CLI
observou a aprovação já existente e criou um único plano; Lead/CTO concluíram
a revisão. O recibo registra `approval_creation_gap_recovered=true`. Não houve
nova aprovação humana ou conserto manual de cards para recuperar essa lacuna.

Essa foi a fronteira da primeira fatia. A materialização e o aceite foram
conectados depois, conforme a prova abaixo. Cancelamento qualificado ainda não
foi implementado; pausa operacional não equivale a cancelar uma release.

## DAG executável e aceite integral — continuação

O contrato opcional `delivery_roles` define `tests` e `integration`, ambos na
matriz de revisão. Exige coordenação e navegador configurados. Não há upgrade
silencioso de instalações: esses papéis mudam o fingerprint do projeto.

```json
{"delivery_roles":{"tests":"quality_security","integration":"devops"}}
```

`releases.py` materializa o plano aprovado, não uma decomposição predefinida pelo
operador. Cada pacote gera teste/Red, implementação/Green e integração/QA, com
revisões nativas independentes. Todos começam estacionados; o grafo imutável só
é ativado depois de completo. Reinício durante a criação não deixa metade das
dependências pronta para despacho. Alteração de corpo, dependência ou workspace
é recusada antes de iniciar um worker de modelo, como indisponibilidade nativa,
sem congelar os slots de outros cards/diagnósticos.

O DAG preserva suas dependências. Nesta primeira stack, acrescenta uma ordem
topológica sequencial às integrações na mesma branch. O pacote seguinte recebe
o snapshot integrado/qualificado do anterior; não usa uma cópia antiga da base.
Não é concorrência de branches arbitrárias ou merge automático de conflitos.
Dois workers continuam sendo teto, não obrigação de paralelismo.

Os contratos de navegador agora podem crescer por arquivos novos
`tests/qa.<identificador>.json`. `qa.json` continua suportado. O controlador
combina todos, exige IDs únicos e mantém o limite de 20 cenários dessa stack.
Arquivos antigos permanecem protegidos, sem permissão para reescrever ou apagar
um cenário anterior. Implementação e revisão recebem o conjunto congelado.

O gate final exige:

- Plano e brief exatos, com cobertura de todos os critérios aprovados.
- Conclusão por execuções independentes reais no Kanban: `done` manual ou run
  sintético não substitui a proveniência de revisão dos pacotes.
- Recibos Red/freeze/Green/controles/revisão vinculados aos respectivos cards.
- Cada base seguinte igual à entrega integrada anterior; suíte cumulativa.
- Publicação, commit de merge, artefato, QA implantado e rollback consistentes.
- QA final cobrindo todos os critérios, não apenas o último pacote.
- Branch ainda no mesmo commit, CI obrigatório verde e o mesmo container/imagem/
  URL qualificados pelo QA ainda saudáveis no instante do aceite.

Somente o controlador grava `release_acceptance` e conclui a âncora. Uma nova
release exige esse encerramento válido, não apenas um `done` bruto. No ensaio,
o recibo exercita o estado `HOMOLOGADA`, mas contém `qualification=true` e
**`delivery_approval=false`**. A notificação diz qualificação determinística,
nunca entrega autônoma de produto. Isso não libera chamadas pagas ou produção.

### Tentativas e causas preservadas

1. **Não aprovada.** Primeiro incremento passou por TDD/integração/deploy/QA. O
   Hermes vinculou legitimamente `completion_contract` à URL exata do PR; a
   primeira conferência do grafo esperava somente o nome do repo. Foi corrigida
   para aceitar a vinculação apenas com publicação/rollout próprios, nunca um
   PR irmão verde. A tentativa foi pausada/drenada antes da correção.
2. **Não aprovada.** QA encerrou na abertura do SQLite, com falso WAL
   "somente leitura". Native retry retomou, mas o roteiro pausou ao detectar o
   crash; não houve aprovação retroativa. Arquivos atuais eram graváveis e o
   WAL já havia desaparecido. Evidências e runs foram preservados.
3. **Passou.** Um experimento controlado reproduziu o preflight upstream:
   fechar a última conexão entre `is_file` e `os.access` faz o WAL desaparecer e
   produz aquela mensagem. Manter outra conexão aberta conserva o WAL e os
   dados. Serviço e worker agora mantêm conexão nativa por sua vida útil, sem
   transação de escrita aberta, chmod, remoção de WAL, retry por texto de erro ou
   patch no Hermes. A tentativa nova concluiu sem crash/reparo do operador.

A prova completa `scripts/qualify_hermes_release.py` verificou:

| Evidência | Resultado |
|---|---|
| Cards | 9: release, brief, plano e 6 cards gerados para 2 pacotes dependentes |
| Runs nativos | 24: 9 conclusões, 8 pedidos de revisão e 7 esperas agendadas |
| SDK/modelo | 11 atividades SDK, 17 respostas locais; zero chamadas pagas ou julgamento real |
| Publicação | 2 PRs simulados distintos; Git e commits de merge reais em remoto bare local |
| Qualidade | Red/freeze/Green/controles/revisão; regressões do primeiro pacote preservadas no segundo |
| Build/operação | 3 artefatos reais, 7 atualizações Compose; reutiliza o candidato anterior como rollback |
| QA | 2 jobs Chromium reais; QA final cobre os 2 critérios no mesmo commit/imagem |
| Aceite | 1 recibo integral de qualificação; não é entrega autônoma ou aprovação de produto |

As implantações temporárias das tentativas foram retiradas após confirmar
ausência de workers/claims/efeitos, com logs e evidências privados preservados.
A URL do ensaio é histórica, não ambiente de homologação disponível ao CEO.
Nenhum volume, snapshot ou recurso de Toso/Reforma foi removido por essa prova.
Após a retirada dos deployments, o plano oficial de imagens removeu cinco
versões antigas desse ensaio; conservou duas recentes, referências protegidas e
imagens em uso. Logs/metadados ficaram arquivados privadamente antes das remoções.

O núcleo atual tem 18 módulos funcionais + `__init__`, 4.301 linhas incluindo a
lane S1. O desvio da meta 12/~3.000 permanece visível. O módulo adicional reúne
materialização e gate final sobre o Kanban, não outro scheduler/DB.

**Continuação:** Produto e planejamento recebem os limites de execução sem
credenciais. Os pacotes recebem arquitetura/observabilidade aprovadas, snapshot
e IDs QA existentes. A base dependente exige QA independente do predecessor
antes de começar, não apenas no aceite final. O relay neutro passou pelo SDK
local; ver [provedor](HERMES-PROVIDER-QUALIFICATION.md) para evidências e limites.

**Continuação do provedor:** a rota e espera/admissão metered já passaram no
worker nativo com dois 402 locais, reinício e TDD completo, preservando sessões,
fase e contador de falhas anterior. Não há instalação paga ou equipe ligada.

**Próxima fronteira:** preparar S4, com autorização explícita, modelo e
GitHub reais. O ciclo offline não substitui esse ensaio, a segunda release com
memória/incidente, instalação reproduzível ou retomada do Truco.

## Interface de planejamento alinhada — 25 de outubro de 2026

O S4 real encontrou uma divergência que as respostas programadas não expunham:
o validador exigia IDs minúsculos sem pontos, mas a ferramenta mostrava somente
`string`. O modelo enviou quatro propostas com IDs incompatíveis e recebeu o
mesmo erro genérico sobre ID/dono, embora os donos estivessem corretos. Nenhuma
proposta foi aceita; houve bloqueio, não um plano falsamente executado.

`draft_schemas` agora usa as mesmas constantes do validador para IDs. Expõe os
donos configurados, critérios do brief exato aprovado, limites de campos,
dependências únicas e formato fechado. O erro distingue `tasks[n].id`, duplicação
e `tasks[n].owner`; não corrige silenciosamente argumentos do modelo. Exemplos
inválidos permanecem inválidos, com diagnóstico que permite ao agente corrigir.

O contrato também explicita a unidade de trabalho: um pacote vertical de
implementação, implantável e testável, não cada passo interno do processo.
Testes, revisões independentes, implementação, CI/deploy e QA já são gerados pelo
controlador para cada pacote. Repeti-los no DAG como pacotes adicionais criaria
decomposição desnecessária e critérios impossíveis de satisfazer parcialmente.
O limite de 24 pacotes permanece; não foram removidos cobertura integral,
revisão do CTO, gates de TDD ou o limite de dois workers.

A prova offline verificou os padrões/enums efetivamente presentes na requisição
do SDK, além de revisão independente, alterações e cobertura: nove atividades,
dez respostas locais e zero chamadas pagas. Não é julgamento real de arquitetura.
As tentativas reais bloqueadas permanecem não qualificadas; o operador não
normalizou/importou o plano nem aprovou em nome de um revisor para obter sucesso.
