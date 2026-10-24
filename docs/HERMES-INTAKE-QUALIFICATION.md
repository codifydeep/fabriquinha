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

**Ainda falta:** materializar o DAG em cards TDD/integradores executáveis,
encadear bases de incrementos dependentes e validar aceite integral para
`HOMOLOGADA`. A âncora `RELEASE` permanece `blocked` no Kanban: não é falha de
worker nem entrega. Não há homologação/cancelamento qualificado aqui; nem um
`done` bruto libera outra release enquanto essa fronteira não existir.

O núcleo passou de 16 para 17 módulos funcionais, além de `__init__`, próximo de
quatro mil linhas incluindo a lane S1. É desvio visível da meta 12/~3.000, não
licença para reconstruir um broker. O módulo novo reúne documentos e a borda
CEO/planejamento sobre APIs nativas; não tem executor ou scheduler próprio.
