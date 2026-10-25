# Integração, espera de CI e QA pelo serviço nativo

Data: 24/10/2026. Continuação de [S3](HERMES-S3-QUALIFICATION.md) e do
[serviço contínuo](HERMES-RUNTIME-QUALIFICATION.md).

Estado desta fatia: **passou em ambiente isolado, sem modelo e com GitHub
simulado**. Não há migração ou liberação de provedor pago. Isso qualifica a
execução mecânica pelo serviço, não uma entrega autônoma por modelos e GitHub reais.

## Fronteira implementada

O mesmo `Runtime` reconhece o modo `integration` a partir do card/claim nativos.
Nesse modo não abre um SDK ou shell para o modelo. Executa as operações fixas já
qualificadas de `Publication`, `Deployment` e `Runner`; autoria/parecer do código
permanecem em cards anteriores com TDD e revisão independente.

```mermaid
flowchart TD
    R[Entrega revisada: dependência concluída] --> K[Hermes Kanban]
    K --> I[Claim de integração: operações fixas]
    I --> P[Publicar PR e conferir CI no SHA exato]
    P -->|Pendente| W[scheduled: run encerrado, capacidade liberada]
    W -->|Prazo registrado e worker anterior morto| K
    P -->|Checks válidos| M[Merge e suíte no commit integrado]
    M --> D[Build por identidade; Compose; rollback e retorno]
    D --> Q[Handoff nativo: QA independente]
    Q --> B[Saúde, identidade, Chromium e captura no mesmo candidato]
    B --> E[Recibo de QA e gate nativo de PR]
    E --> A[Aceite integral da release ainda separado]
```

- A integração exige o contrato nativo de conclusão por PR do repositório, não
  `local-only`. O recibo de entrega é resolvido de um pai concluído e validado
  contra projeto, release e revisão independente antes da publicação.
- `Pending` externo encerra a claim via `schedule_task`. O motivo referencia um
  recibo imutável com projeto, contrato, responsável, run e horário de retomada.
  Não há tabela/estado de workflow adicional ou worker fazendo polling de CI.
- O tick usa `unblock_task` somente para essa espera reconhecida. Reconfere a
  última tentativa, atribuição, contrato e identidade do worker. Não desbloqueia
  credenciais, falhas técnicas ou decisões humanas como se fossem espera de CI.
- O upstream pode limpar os campos PID de uma tentativa encerrada. Nesse caso,
  a identidade vem do evento nativo `spawned`/`worker_registered` do mesmo card e
  run. PID nulo não prova morte; PID reciclado não herda a identidade original.
- Efeitos já aceitos são reobservados pelo journal existente; prazos originais de
  PR/CI/build/deploy não recomeçam porque uma nova claim foi criada.
- O guard upstream `active_pr` fica intacto. Recibos e metadata carregam a relação
  com o PR; não se adiciona um comentário de URL para forçar um respawn. Uma
  intervenção externa que acione esse guard permanece visível, sem bypass.
- Jobs locais de suíte/navegador são computação real, com espera limitada ao
  prazo do executor. A revisão não usa `scheduled`, que perderia a fase no
  upstream fixado. Uma pendência inesperada no QA continua bloqueada/visível.
- QA usa o perfil independente da matriz, testa a imagem/commit implantados,
  confere CI do merge novamente e conclui pelo gate nativo de PR. Isso produz
  `release_evidence`, não declara automaticamente `HOMOLOGADA`.

## Prova e limites

O roteiro `scripts/qualify_hermes_integration.py` parte do TDD determinístico S2,
com Red/Green, congelamento, controles negativos e pareceres sintéticos. Depois
cria somente o card inicial de integração. Claims, esperas, retomadas, publicação,
handoff de QA e conclusão desse card pertencem ao serviço real.

O transporte GitHub da fixture é persistido entre processos; simula confirmação
perdida e checks pendentes. Não é instalado como opção do serviço de produção.
O código normal continua usando GitHub CLI e não permite escrever no GitHub real
quando `qualification=true`. Não existe endpoint de CI falso na configuração
de produção.

A primeira tentativa chegou ao QA, mas falhou na auditoria do verificador porque
os PIDs já haviam sido limpos pelo upstream. Ficou registrada como não aprovada;
seu deploy e redes vazias foram retirados após conferência das identidades pelos
eventos nativos, preservando evidências, imagens e snapshots. A correção foi
testada antes de uma nova tentativa, não aplicada para aprovar a prova antiga.

A segunda tentativa completou a cadeia sem reparo ou handoff do operador:

1. O serviço criou um PR pela fixture; a confirmação foi perdida depois do
   aceite. A claim foi encerrada em `scheduled` e outra reobservou o mesmo PR.
2. CI ainda pendente provocou outra espera sem run aberto. O dispatcher terminou
   normalmente; a fixture disponibilizou checks verdes e outro dispatcher
   retomou a espera pelo horário persistido, sem `unblock` manual.
3. Git real registrou a proposta e o merge; o executor conferiu CI no SHA de merge
   e reexecutou a suíte completa. Houve um único PR e um único merge simulados.
4. Dois builds reais produziram baseline/candidata. Quatro operações Compose
   fizeram bootstrap, candidata, rollback e retorno, observadas em novas claims
   sem repetir os efeitos já aceitos.
5. O handoff nativo atribuiu QA a outro perfil. Chromium exercitou o comportamento
   HTTP, gerou captura e conferiu a mesma imagem/commit. O gate nativo de PR
   aceitou a conclusão do card, sem declarar uma release homologada.
6. Foram nove runs de integração: seis `scheduled`, um `crashed`, um handoff de
   revisão e um QA concluído. O crash de inicialização foi recuperado nativamente,
   sem reparo do operador. O erro reportava `-shm` não gravável; os arquivos
   posteriormente estavam graváveis. O preflight upstream verifica arquivos
   transitórios em passos separados: uma corrida de desaparecimento do sidecar
   é hipótese plausível, não causa causalmente comprovada. Não se apagou WAL/SHM,
   alterou permissão ou adicionou retry específico para converter o resultado.
7. Serviço e workers terminaram, sem claims abertas. Logs/metadados foram
   preservados e o deploy descartável e suas duas redes vazias foram retirados
   por identidade exata. O demo anterior continuou saudável; Toso e legado não
   foram alterados. A limpeza ficou restrita aos recursos desta qualificação.

A observação operacional deve usar o `runtime status`/API nativa, não abrir o
banco vivo com uma CLI SQLite independente. O erro transitório e a primeira
tentativa permanecem no histórico; não se relata um ensaio sem falhas. O
denominador desta qualificação é duas tentativas, uma aprovada no escopo acima.

Oito testes de regressão novos cobrem contrato nativo de PR, espera durável,
conservação de fase, atribuição/contrato alterados, identidade após limpeza de
PID, ausência/divergência de evento de spawn, prazo local e QA no SHA integrado.
Total: **125 testes do caminho novo**, sem falhas ou skips; **4.523 históricos**,
com oito skips preexistentes e nenhuma falha. Nenhum teste foi removido.

## Reprodução

Use os ambientes/imagens fixados das qualificações anteriores e uma raiz nova.
Faça as prévias de limpeza do `AGENTS.md` antes/depois. O roteiro retira somente
seu deploy descartável e redes próprias vazias ao término, após arquivar logs e
conferir ausência de claims, workers e efeitos pendentes. Nenhum volume ou
snapshot é removido; a URL retirada é evidência histórica, não serviço disponível.

```bash
HERMES_DISABLE_LAZY_INSTALLS=1 .local-hermes-agent/venv/bin/python \
  scripts/qualify_hermes_integration.py \
  --upstream .local-hermes-s1/upstream --root .local-hermes-integration/trial-new \
  --image sha256:ID_EXATO_DO_VALIDADOR \
  --browser-image sha256:ID_EXATO_DO_BROWSER
```

## Próximos limites

A [pausa/retomada e admissão](HERMES-OPERATIONS-QUALIFICATION.md) passaram depois,
com limites próprios documentados. Brief/plano/aprovação exata e aceite integral
passaram depois em [intake/release](HERMES-INTAKE-QUALIFICATION.md). Incidentes de integração
ainda não percorrem todo o diagnóstico técnico qualificado para TDD. Telegram,
modelo e GitHub reais, segunda release/memória e instalação portátil permanecem
pendentes. Não converter essas lacunas em mais uma rodada de controles genéricos
antes da primeira entrega pequena S4.

O código ativo tem 15 módulos funcionais, 3.310 linhas físicas incluindo a lane
S1 e `__init__`. A conexão acrescenta cerca de 120 linhas ao módulo operacional,
sem novo módulo/coordenador/DB. O desvio de aproximadamente 310 linhas da meta
inicial de 3.000 continua explícito; não é motivo para minificar o código nem
evidência de autonomia.

## Computação local de CI antes de S4

`LocalCI`, no módulo de publicação, executa um comando fixo usando o mesmo
validador isolado do TDD. Não registra runner, publica status GitHub, altera
proteção de branch ou concede permissão de merge. O CLI
`scripts/check_hermes_ci.py` é uma operação do controlador, não uma ferramenta de
shell para os agentes. A instalação paga permanece desabilitada.

O chamador confiável fornece head/base autenticados do PR ou merge. A computação:

1. Confere a branch atual, exporta Git por SHA e exige ancestralidade da base.
2. Preserva arquivos de testes e configurações, inclusive `.github`, antes de
   executar código. Uma nova configuração protegida também não é aceita.
3. Executa a suíte completa da base e do candidato em jobs separados, sem rede,
   credenciais ou socket, usuário `65534`, árvore somente leitura e limites.
4. Exige base verde, casos não vazios/únicos, ausência de erros/skips e preservação
   de todos os casos antigos na descoberta. Uma assertion falha produz conclusão
   `failure`, não sucesso. Uma configuração inválida não gera recibo verde.
5. Confere proveniência dos jobs e revalida a branch após o teste. Commit/base
   obsoletos não recebem aprovação, mesmo com suíte verde.

O journal permite observar/reutilizar o mesmo job, sem executar novamente por
perda de resposta. Base, proposta e commit integrado têm escopos próprios. Os
recibos usam `scope=local_ci`, não fingem ser execuções nativas de um autor ou
revisor; não podem substituir Red, freeze, revisão independente ou aceite final.
As mesmas verificações de relatório foram extraídas do gate TDD sem retirar
condições. CI continua sendo evidência separada, não autorização de entrega.

A prova `scripts/qualify_hermes_ci.py` passou com remoto bare local e sete jobs
Docker reais: proposta válida/reutilizada, SHA integrado, assertion falha, skip,
alteração de teste antigo recusada antes do job e redução de descoberta recusada.
O último controle adiciona um módulo que esconde a classe antiga do loader sem
editar seu arquivo: comparar somente hashes não bastaria. Todos os jobs próprios
foram arquivados/retirados; nenhuma imagem, volume ou snapshot foi apagado.
Uma primeira fatia mais curta havia passado com quatro jobs; a prova ampliada
não é uma execução de produto nem publicação de check no GitHub.

**Limite atual:** a computação está qualificada, mas não foi conectada a um check
obrigatório real. A origem do check na nova branch exige escolha explícita do
proprietário; não alterar a `main` nem afrouxar seus checks existentes. Está
proposta publicação de status no SHA pelo controlador local em vez de registrar
um runner Actions público. O [GitHub recomenda evitar runners próprios em repos
públicos](https://docs.github.com/en/actions/reference/security/secure-use), pois
workflows não confiáveis podem comprometer o ambiente. Um runner compartilhado
do Truco não deve ser reaproveitado por conveniência.

Antes da publicação real, o contrato deverá vincular o check ao recibo, SHA,
base e projeto exatos e observar envios com ACK incerto. Só então configurar a
branch nova e iniciar S4 autorizado. Não substituir esse passo por marcar check
verde manualmente ou aceitar um recibo de CI como parecer independente.
