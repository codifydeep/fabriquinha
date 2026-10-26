# ADR 0005 — Validação fixada e custos observáveis

Estado: implementação do P2 aprovado na revisão de 26/10/2026. Não altera escopo
de produto, modelo, cotas, autorizações de negócio ou resultados históricos.

## Bundle de validação

Uma instalação nova captura `suite.py` e `browser.py` do controlador em um
snapshot do Store. O campo `validation_bundle` de `installation.json` identifica
esse snapshot; `control_contract` identifica a semântica de qualidade aprovada.
O arquivo já existente continua sendo a referência da instalação: não há outro
banco, registro de plugins ou serviço para selecionar validadores.

Cada job registra o bundle exato. Baseline, Red, Green, controles, revisão e CI
montam os scripts fixados somente leitura. O QA implantado usa o mesmo driver
fixado. O snapshot do produto, suas credenciais e seu socket Docker continuam
separados desses scripts e do controlador.

Editar o checkout depois da preparação não altera esses mounts nem reinterpreta
uma evidência anterior. Conteúdo adulterado no bundle, projeto divergente ou
recibo de outro bundle são recusados. Alterar a semântica de qualidade exige
versão explícita do contrato e migração/qualificação; atualização operacional
não instala automaticamente um novo gate numa execução ativa.

Instalações anteriores sem bundle continuam reconhecidas como legadas para
consulta das provas. Admissão de trabalho real exige bundle; não é permitido
acrescentar um pin a uma instalação antiga e converter suas aprovações. A
homologação assistida pelo PR 57 permanece válida no contrato em que foi executada.
Migração geral e rollback de upgrade continuam pertencendo a S6.

O pin vale para todas as execuções da instalação enquanto não houver uma
migração explícita. Cada execução o referencia em suas provas; a instalação
pode ser reutilizada na segunda versão sem mudar seu validador silenciosamente.
Isso fixa os scripts executados e a versão declarada de qualidade, não todo o
Python do controlador nem uma prova de equivalência semântica de qualquer update.

## Contabilização

O relay mantém sua única tentativa por envio e seu contador durável. Além dos
totais de tokens, preserva campos permitidos da resposta: ID da geração, custo
reportado, tokens de cache e tokens de raciocínio. Respostas e ferramentas não
são reescritas. Não são guardados prompts, respostas textuais ou headers completos.

O SDK recebe um header local com o hash de um recibo `model_activity`. Esse
recibo vincula a chamada à execução, card, perfil e fase. O relay grava apenas
o hash e não o encaminha à OpenRouter. A atribuição serve para contabilização;
nunca autoriza ferramenta, revisão, merge ou mudança de estado no Kanban.

O endpoint local autenticado `/usage` agrega somente tentativas registradas para
o projeto da política. `runtime costs` resolve os hashes nos recibos privados.
O relatório funciona durante pausas e não habilita política, consulta chave do
provedor, faz inferência ou solicita metadados de geração à OpenRouter.

```bash
PYTHONPATH=src <python-do-SDK> -m fabriquinha.runtime costs \
  --root <instalacao-privada> --upstream <checkout-Hermes-fixado>
```

Regras de leitura:

- `known_cost_usd`: soma decimal somente dos custos reportados pelo provedor.
- `unknown_cost_calls`: tentativas sem custo válido, incluindo transporte incerto.
- `recorded_total_cost_usd`: nulo se alguma tentativa registrada não tiver custo.
- `global_unrecorded_calls`: lacunas históricas do contador compartilhado, que não
  podem ser atribuídas honestamente a um projeto nem tratadas como gasto zero.
- `token_reporting_calls`: quantas tentativas informaram cada contador; soma
  parcial de cache não implica que as outras tentativas tiveram cache zero.
- Tokens de raciocínio/cache são detalhamentos: não devem ser somados outra vez
  ao total de tokens para estimar cobrança.

Zero efetivamente reportado é diferente de ausência. Dados antigos não recebem
estimativas retroativas. Falhas 402 e transporte incerto conservam suas barreiras
e suas chamadas consumidas. O relatório não substitui fatura nem cria um teto
monetário; o limite autorizado de chamadas permanece independente do custo.

A [documentação de uso da OpenRouter](https://openrouter.ai/docs/cookbook/administration/usage-accounting)
descreve os detalhes devolvidos na resposta; seu sistema de créditos é denominado
em USD, conforme o [suporte oficial](https://openrouter.ai/support/). Não há tabela
de preços ou desconto de cache presumido no código.

## Provas e fronteiras

- Testes cobrem edição do checkout, adulteração do bundle, evidência obsoleta,
  mounts de todas as fases e continuidade da observação de CI sob o mesmo pin.
- `qualify_qa_correction.py --pinned` executa treze jobs Docker/Chromium e recusa
  uma contradição QA; a CI integrada continua usando o snapshot fixado mesmo
  quando o checkout simulado passa a conter scripts que falhariam ao executar.
  A prova passa pela entrada `LocalCI.validate` com Git real, tanto com testes
  novos adicionados quanto com uma expectativa QA preexistente corrigida e
  revisada. A adição normal não recebe nem exige a exceção corretiva.
- `qualify_hermes_intake.py --neutral-relay` exercita nove atividades SDK nativas
  e onze respostas HTTP locais. Verifica o header, a atribuição e custo sintético,
  preservando uma pausa financeira e recusando leitura sem autenticação.

As provas usam decisões/respostas programadas, zero chamadas pagas e nenhuma
aprovação de entrega. P2 não qualifica o julgamento real nem o S4 sem intervenção.
