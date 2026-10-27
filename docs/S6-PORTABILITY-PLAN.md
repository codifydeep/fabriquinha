# S6 — Instalação reproduzível e operação da equipe

## Ponto de partida

S4 tem uma entrega técnica sem intervenção após o aceite. S5 entregou a segunda
versão com dois pacotes, regressões preservadas, memória e recuperação reais,
mas registrou sete intervenções. Não repetir outro ensaio genérico nem tratar
os bancos privados existentes como instalador. O resultado e os limites estão
em [S5](HERMES-S5-QUALIFICATION.md).

O próximo objetivo é permitir a outra pessoa reproduzir o fluxo a partir do Git,
com seu repositório e credenciais. Manter Hermes + Kanban, um controlador e o
relay existente. Não adicionar orquestradores, filas ou bancos paralelos.

## Sequência e evidências

| Etapa | Trabalho | Evidência exigida |
|---|---|---|
| S6.1 — Atribuição auxiliar | Ativar conjuntamente o SDK e relay com endereço de atividade; preservar o contador e seus marcadores | URI/header consistentes, compressão atribuída, nenhuma nova chamada de worker sem escopo; histórico sem origem não é reatribuído |
| S6.2 — Preparação pública | Consolidar a entrada atual `prepare_hermes_project.py`, receitas de imagens e configuração de exemplo | Clone limpo, Hermes fixado e sem patches, imagens construídas por instruções públicas, raiz privada nova, sem UUIDs/caminhos/bancos da instalação anterior |
| S6.3 — Operação | Qualificar doctor/start/status/pause/resume e manutenção da fonte | PID/fingerprint verificados, um dono da instância, estado persistente, código imutável, pausa drenada e retorno idempotente |
| S6.4 — Outro repositório | Executar a entrada pública contra outro repo autorizado, com branch própria | PRs/revisão/CI reais, dois incrementos dependentes, QA/rollback e regressões no mesmo SHA; nenhuma edição manual do produto |
| S6.5 — Canais | Conectar intake, perguntas e entrega ao destino autorizado; manter execução independente de falha de envio | Mensagem recebida no canal real, resposta humana vinculada à pergunta/escopo corretos, fila persistente e deduplicação; recebimento não é presumido pelo enqueue |
| S6.6 — Upgrade e corte | Atualizar/reverter o código com preservação de estado e retirar serviços legados sem uso | Backup restaurado em isolamento, mesma cota e dados, proteção de leases, volumes/rollback retidos e nenhuma dependência operacional do legado |

S6.1 tem implementação e provas locais preparadas no
[ADR 0005](ADR-0005-VALIDATION-AND-ACCOUNTING.md), mas falta ativação conjunta e
qualificação do novo caminho real. Um relay antigo deve bloquear o novo SDK no
preflight, sem consumir chamadas. Não iniciar paid dispatch para descobrir uma
incompatibilidade já observável por metadados.

### Entrada de fonte e operação

S6.2/S6.3 agora dispõem de `fabriquinha.source freeze/verify` e da entrada pública
`scripts/run_hermes_runtime.py`. O export usa um commit completo e uma lista
fechada de caminhos; um hash externo verifica conteúdo, links, permissões e
arquivos extras. Os comandos existentes são reutilizados, sem outro daemon,
gerenciador de PID ou banco. `serve` preserva a pausa, e workers recebem o mesmo
pin. A prova nativa de operação está em `scripts/qualify_source_operations.py`;
sucesso nessa fronteira não conclui a instalação, upgrade ou entrega real de S6.
Instruções em [SETUP](SETUP.md).

**Prova de 27/10:** revisão `786e16d76f1e506a63431165ba12bf0471f95dd4`, 36
arquivos exportados e Hermes upstream sem patches. Um clone Git local novo e
board nativo vazio comprovaram início pausado, recusa de segundo dispatcher,
persistência da pausa após reinício, recusa de episódio obsoleto e rejeição de
conteúdo alterado no export. Os dois processos próprios terminaram normalmente;
nenhum worker foi criado. Zero chamadas ao modelo, operações GitHub ou jobs
Docker. A suíte do núcleo passou em 360 testes, também sem `site-packages`.

Isso qualifica a entrada operacional nessa condição pausada, não o instalador
completo, execução paga, todos os caminhos de doctor/retomada ou serviço do host.
O relay e a homologação da instalação anterior não foram alterados; o contador
permaneceu em 6.951/7.000. O primeiro ensaio local selecionou uma revisão antiga
antes do fim do commit e foi recusado por ausência de inputs obrigatórios; foi
preservado como falha de preparo, sem promoção de evidências.

### Próximo bloco antes da ativação

**Toolchain público preparado:** `Dockerfile.validation-browser` passou a derivar
do digest público Python, com Playwright 1.64.1 e wheels transitivos fixados por
hash. Seus alvos `validation` e `qa` foram construídos em Linux ARM64 sem imagens
de Reforma ou Toso. Quatro jobs de TDD passaram, incluindo Red comportamental,
Green, controle negativo e preservação do teste auxiliar. Um probe separado
executou o driver QA real no UID 10000, sem rede externa. Todos os jobs foram
retirados; imagens instaladas no S5 não mudaram. Build público não implica
determinismo bit a bit das bibliotecas Debian ou qualificação de outra arquitetura.
Instruções e limites em [SETUP](SETUP.md#imagens-públicas-da-stack-pythonhttp).

**Perfis preparados e qualificados:** a fonte gerenciada produz o `config.yaml`
e fixa `profile_contract` na instalação nova. Preflight e worker recusam configuração
divergente, rota/modelo auxiliar explícito, fallback ou extensão não qualificados,
sem reutilizar o last-known-good como configuração válida. Status expõe motivo,
responsável e próxima ação por perfil; um problema local não cria uma barreira
para papéis independentes. A fonte nova não ativa trabalho real em instalação
histórica sem esse pin.

Uma prova com o preparo público criou nove perfis novos, verificou os defaults
efetivos do Hermes e a recusa de fallback nativo. O Kanban recusou o perfil
divergente e admitiu outro no mesmo tick, sem gastar falha funcional; esse callback
não criou worker. Em outra prova, o contrato acompanhou oito atividades SDK reais,
19 respostas HTTP locais e TDD completo, incluindo pausa durante autoria/revisão,
reinício, perfil revisor ausente e retomada. Nenhuma chamada paga, alteração GitHub
ou homologação de produto. A suíte do núcleo chegou a 371 testes, também com `-S`.

1. Preparar uma raiz nova usando os comandos públicos e a mesma fonte no SDK e
   relay. Qualificar operação/restauração e reservar o ciclo real antes de ativar
   consumo. Não mudar a fonte instalada do S5 apenas para atualizar documentação.
2. Verificar provisionamento de redes, estado/credenciais externos e comandos de
   bootstrap no outro repositório autorizado, sem dependência de bancos históricos.

## Decisões para a execução

- Usar as entradas existentes e reduzir passos manuais. Não criar outro serviço
  apenas para reunir os comandos do operador.
- Fazer a preparação ser verificável e não iniciar inferência implicitamente.
  Mostrar pendências concretas em doctor, com comando de recuperação suportado.
- Gerar perfis a partir de configuração versionada. Validar divergências de
  ferramentas e rotas auxiliares antes de habilitar consumo; rotas explícitas
  fora do relay não pertencem à qualificação de herança do compressor.
- Congelar a fonte e qualificar SDK/relay como um conjunto. Preservar o bundle
  de testes; mudanças semânticas exigem sua migração própria.
- Identificar o repo/branch e orçamento antes da ativação. Não apagar ou modificar
  main de produto para facilitar o ensaio. Não transpor a aprovação de um brief
  para outro conteúdo/projeto sem autorização correspondente.
- Injetar falhas controladas em fixtures e pelo menos uma recuperação na execução
  relevante, sem matar processos alheios ou requisição financeira incerta.
- Auditar custos por diferenças entre checkpoints e escopos novos. Os 15 registros
  históricos sem atividade permanecem visíveis; não exigir apagá-los para uma
  janela nova demonstrar ausência de novas lacunas.
- Preservar projetos Toso/reforma, volumes, snapshots, deployment e rollback.
  Retirar somente recursos comprovadamente próprios e ociosos por seus IDs.

## Saída e limites

A conclusão exige instruções públicas suficientes para instalar em outro local,
operar e recuperar a equipe e entregar pela mesma entrada. Uma prova programada
com transporte falso não substitui essa entrega real. A aprovação técnica do
instalador também não dispensa os gates do produto ou a aprovação de negócio.

A instalação de referência encerrou S5 em 6.951/7.000 chamadas: restam 49.
Esses valores são um checkpoint, não uma autorização para novas instalações ou
um limite de dólares. Reservar o orçamento do ciclo antes da ativação; se não
couber, continuar offline e pedir a autorização específica necessária.

Só depois da evidência de S6, retomar o Truco por Produto a partir das informações
já fornecidas pelo CEO. A stack Python/HTTP atual não qualifica automaticamente
outros adaptadores, mobile, 3D, colaboração paralela ilimitada ou ausência universal
de starvation diante de dependências externas.
