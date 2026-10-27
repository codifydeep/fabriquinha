# Revisão antes do S6 — 27 de outubro de 2026

Estado: **refinamentos e plano aprovados pelo proprietário em 27/10/2026**.
F2/F3 estão no [ADR 0006](ADR-0006-SHARED-ACCEPTANCE.md), em implementação e
qualificação offline. O restante preserva o estado auditado; recomendações não
constituem evidência de conclusão. O aceite não eleva cotas nem converte provas.
O CEO aprovou o escopo do brief S6. O estado abaixo é o retrato da auditoria;
a execução posterior, incluindo aceite aplicado e manutenções, está no
[status atualizado](STATUS.md). Nenhuma evidência da auditoria é convertida
retroativamente em entrega.

## 1. Parecer

**Manter Hermes + Kanban. Não iniciar a execução S6 com o contrato atual de QA.**
A simplificação de plataforma foi correta e produziu evidência melhor que a
arquitetura anterior: há uma entrega técnica limpa S4 e uma continuidade S5
efetivamente homologada. Entretanto, S5 exigiu sete intervenções externas.
Preparar uma instalação nova não elimina as limitações que essas intervenções
expuseram. A execução está cuidadosa na preservação das provas, mas ainda reage
a incompatibilidades de protocolo depois de gastar trabalho dos agentes.

Dois problemas verificáveis devem ser resolvidos antes de ligar o despacho:

1. O QA implantado não representa a colaboração entre navegadores e o prazo de
   atualização que o brief S6 exige.
2. A correção recente da redação do brief voltou a exigir CEO para toda alteração
   de teste, conflitando com a autoridade técnica já aceita no ADR 0004.

A recomendação é remover essa incompatibilidade, consolidar a operação pública
essencial e executar o S6 existente. Não trocar novamente de ferramenta, modelo,
board ou objetivo. Não abrir outra sequência de ensaios genéricos.

## 2. O que evoluiu de fato

| Fronteira | Evidência conferida | O que não significa |
|---|---|---|
| Hermes nativo | Kanban/SDK sem patches upstream; controlador novo sem outro banco de tarefas | Autonomia universal ou todos os recursos nativos habilitados |
| S4 | PR 59, nove testes, revisão, CI, deploy, rollback e QA; zero intervenções técnicas após aceite | Descoberta nova de produto: o brief foi reutilizado sob autorização exata |
| S5 | Reset/Undo, PRs 60/61, 29 testes, oito critérios QA, regressão preservada e recuperação real | Ciclo autônomo limpo: houve sete intervenções de manutenção |
| Preparação S6 | Clone público, raiz e sessões novas, upstream fixado, perfis e identidade GitHub verificados | Instalador completo utilizável sem conhecimento do operador |
| Atribuição S6 | Duas chamadas reais de Produto atribuídas por atividade; custo reportado | Compressão real qualificada nesta janela ou reatribuição do histórico |
| Recuperação da instalação | Backup extraído, SQLite íntegro, leitura nativa dos cards/pausa | Retomada de trabalho em andamento após desastre ou reinício do host |

Fonte auditada: `fabriquinha/main` em `000b5c5a42e426139e3d7f369a9c91f7bbf9bad5`;
instalação S6 exportada de `820e38f297425d50663e65fc6edc7f6044bb1d4a`.
Os 386 testes previamente aprovados do núcleo são evidência de mecanismos;
esta auditoria não os reexecutou nem os usou como porcentagem de autonomia.

Durante a auditoria foi completada a parada operacional: controlador e relay S6
parados, política de provedor desabilitada, sem workers. A pausa durável já
existia. Homologação S5 e recuperação foram preservadas. Não houve inferência.

## 3. Achados prioritários

### A1 — O executor de QA não consegue provar o requisito central de S6

Em [browser.py](../src/fabriquinha/browser.py), o contrato aceita somente ações
`fill`/`click` seguidas de uma comparação de texto. O executor cria um único
`BrowserContext` e uma única página, reutilizados entre cenários. Não há ações
para abrir sessões independentes, alternar jogadores ou medir um intervalo
desde uma ação até a observação em outra sessão.

S6 exige dois navegadores independentes, os mesmos participantes vistos por
ambos, recusa de terceiro jogador e atualização em até três segundos. Os testes
Python autorais podem expressar isso, mas o QA **do ambiente implantado** passa
pelo interpretador limitado. A asserção final espera até cinco segundos e não
mede o prazo de negócio desde o evento. Portanto, um QA verde nesse formato não
prova os três segundos nem o comportamento entre sessões independentes.

Há outras restrições relevantes:

- Navegação espera `networkidle`. Polling/long polling pode conflitar com essa
  condição. O próprio Playwright recomenda asserções de prontidão, em vez de
  `networkidle`, para testes: [documentação oficial](https://playwright.dev/docs/api/class-page).
- Cookies/storage e estado do servidor podem contaminar cenários. Uma nova
  página não limpa dados do servidor; criar contextos também não resolve isso
  sozinho. Casos de lista vazia e de sala existente precisam de fixtures claras.
- O contrato exige uma checagem declarativa por ID, mas critérios como preservação
  da regressão são propriedades da entrega, não um texto que deve aparecer na UI.
- WebSockets são recusados explicitamente. Isso é um limite válido da stack
  HTTP qualificada, mas deve ser informado ao planejamento, não descoberto por
  tentativas de implantação. S6 pode usar HTTP; não exige liberar WebSockets.

O problema não é falta de inteligência do modelo. A equipe foi encarregada de
produzir prova em uma linguagem que não representa a prova solicitada. O
`doctor` atual confere infraestrutura e configuração, não essa compatibilidade.

**Recomendação F2:** usar uma suíte de aceitação Playwright/Python congelada,
parametrizada pelo endereço do aplicativo, na prévia e no QA implantado. Reusar
o executor fixo e isolamento existentes. Manter testes unitários/integração
quando úteis; unificar a expressão da aceitação de navegador, não todos os
tipos de teste. O Playwright já suporta múltiplos contextos isolados no mesmo
teste: [documentação oficial](https://playwright.dev/docs/browser-contexts).

Não transformar isso em execução arbitrária no controlador: o comando é fixo;
testes e entrega são imutáveis; o container não recebe credenciais, socket ou
rede externa. O acesso de QA fica restrito ao aplicativo da execução. Hashes,
SHA, descoberta integral, ausência de skips, erros e resultado real continuam
verificados fora do controle do agente. Saúde/identidade do deploy continuam
sendo verificações independentes dos testes autorais.

Adicionar contextos, temporizadores, condições e variáveis ao JSON seria uma
correção possível, mas faria crescer uma linguagem de testes própria. Preferir
remover essa duplicação. A substituição é uma proposta de contrato, ainda não
implementada; deve ser qualificada offline antes de qualquer novo despacho.

### A2 — A intervenção do operador reintroduziu uma dependência indevida do CEO

O [ADR 0004](ADR-0004-SCOPED-REPAIR.md), aceito em 26/10, permite correção técnica
justificada por brief, com nova revisão independente e histórico preservado.
O CEO decide alterações de negócio e exceções que removam cobertura.

O primeiro brief S6 tinha uma permissão vaga de exceção pelo revisor. Foi correto
questioná-la. Entretanto, a devolução levou a uma redação que exige aprovação do
CEO para **qualquer** mudança intencional em testes/QA herdados. Isso foi longe
demais: conflita com o ADR aceito e com o reparo implementado. A inconsistência
foi introduzida na condução do processo, não pode ser atribuída somente ao modelo.

**Recomendação F3:** harmonizar a governança sem mudar os requisitos de produto:

| Situação | Autoridade e prova |
|---|---|
| Testes novos antes de freeze | Autor corrige; revisor independente avalia |
| Snapshot congelado | Ninguém altera no lugar; correção gera nova revisão |
| Expectativa técnica derivada errada, sem alterar brief/cobertura | Lead classifica; revisão independente; CTO resolve ambiguidade; novo freeze e todos os gates |
| Remoção de cobertura ou mudança de negócio | Card justificado e aceite explícito do CEO |
| Reparo que o executor não suporta | Impedimento técnico explícito; não inventar permissão nem solicitar que o CEO depure o sistema |

A capacidade atual do ADR 0004 é estreita: alterações autorizadas de `text` em
arquivos QA existentes após falha de QA implantado do último pacote, mantendo
IDs, seletores, ações e testes Python. Isso **não** autoriza correção arbitrária
de testes Python. Migrar para F2 exige declarar como esse reparo estreito será
tratado; não presumir equivalência automática entre JSON e código de teste.

Para o primeiro S6 sob F2, preferir manter o reparo `product` já qualificado e
recusar explicitamente reparos sem suporte. Testes novos podem ser corrigidos
antes do freeze. A revisão técnica de uma suíte congelada em Python exige um
contrato próprio de nova revisão e qualificação, se um caso real a exigir; não
construir agora um analisador universal de equivalência de testes.

O aceite do brief S6 está preservado. Não reescrever o documento aprovado em
silêncio. Registrar F3 como harmonização de governança submetida ao proprietário,
sem pedir novamente apelidos, escopo ou regras já respondidas.

### A3 — A operação ainda depende de conhecimento privado do operador

O preparo público, os exports imutáveis e o vínculo explícito da identidade
GitHub são avanços corretos. Contudo, a instalação/cutover bem-sucedidos ainda
usaram auxiliares privados para partida, troca de relay, verificações e parada.
Uma pessoa com apenas o clone não dispõe de toda essa sequência consolidada.

`pause` significa suspender admissão e drenar, não desligar serviços. Nesta
auditoria foi necessário completar a parada de controlador/relay e desabilitar
a política. Isso não prova gasto indevido; prova que as três condições devem
ser distintas no status: **trabalho pausado, chamadas desabilitadas, serviços
parados**. Um comando de operação deve verificar o resultado que promete.

O medidor deliberadamente exige estado existente e não o reseta. A instalação
S6 reutilizou os volumes privados de medição/chave. Isso é correto nesta
migração, mas não demonstra bootstrap de um usuário novo. Documentar/criar
inicialização explícita exclusiva de raiz vazia, com orçamento escolhido pelo
operador; nunca reaproveitar esse caminho para zerar um medidor existente.

Em [runtime.py](../src/fabriquinha/runtime.py), `serve` é um processo foreground.
Há tratamento localizado de falhas, mas exceções não tratadas em `tick`/status
podem terminar o laço. Recuperação de worker não prova supervisão do controlador.
Para operação sem acompanhamento, usar um gerenciador padrão da plataforma
suportada, com atraso de reinício e preservação da pausa. Não criar outro daemon
de recuperação ou um loop de restart infinito para erro de configuração.

A saída de S6 deve distinguir: instalação nova, operação persistente,
recuperação de processo e entrega de produto. Nenhuma dessas substitui as demais.

### A4 — A memória configurada é menor que a equipe originalmente imaginada

O SDK é instanciado com `skip_memory=True`, `skip_context_files=True` e revisão
de background desligada. Brief/plan não têm ferramentas genéricas de leitura
de arquivos. Os SOULs, skills e memórias antigas dos nove perfis não devem ser
apresentados como ativos automaticamente nesse caminho.

Há memória útil e verificável: `Intake.previous` recupera a **última** release
aceita, valida proveniência e fornece resumo de brief, IDs, arquitetura e
observabilidade. S5 provou esse uso. Isso não é uma memória cumulativa de produto,
ADRs e decisões de muitas versões; uma decisão antiga que não seja repetida
na última release pode deixar de ser apresentada ao planejador.

Preservar a proteção contra instruções históricas e aprovações herdadas. A
evolução recomendada é pequena: documentos canônicos de produto/arquitetura e
índice de ADRs no Git do produto, lidos pelo planejamento no SHA-base, com limites
de tamanho e proveniência. Atualizações seguem PR/revisão; decisões substituídas
ficam identificadas. Não ligar leitura irrestrita de todo o home, inserir
transcrições no prompt, criar banco vetorial ou agente de sumarização contínua.

Essa extensão é necessária antes de prometer muitas versões autônomas, mas não
precisa bloquear a primeira entrega S6 de dois incrementos. Registrar o limite
agora e validar retenção de decisão de duas versões atrás na etapa seguinte.

### A5 — A complexidade voltou a crescer; não por uma nova plataforma

Contagem estática dos arquivos Git rastreados nesta revisão:

| Área | Medida |
|---|---:|
| Núcleo `src/fabriquinha` | 24 módulos Python; 7.227 linhas físicas |
| Núcleo em `c9144c68`, referência da revisão anterior | 20 módulos; 5.779 linhas |
| Crescimento | 1.448 linhas, aproximadamente 25% |
| Testes do núcleo | 47 arquivos Python; 6.082 linhas |
| Scripts públicos | 34 arquivos Python; 4.860 linhas |
| Diretório legado `team-delivery-kit` | 1.947 arquivos; 176.362 linhas Python |

As contagens medem superfícies diferentes, não produtividade nem defeitos. O
núcleo novo permanece muito menor que o legado, mas ultrapassou a meta inicial
de 12 módulos/3.000 linhas. Essa meta era uma restrição de desenho, não um motivo
para compactar código, esconder linhas ou retirar segurança. Parte da expansão
é legítima: configuração, identidade, reparo e operação antes não estavam
completamente representados.

O risco é continuar adicionando um adaptador para cada recusa. A simplificação
de maior retorno agora é uma representação de aceitação e um contrato de
autoridade. Depois, retirar o legado do caminho de instalação e da árvore ativa,
preservando Git/recuperação e compatibilidade dos auxiliares ainda utilizados.
Não mover caminhos operacionais ou apagar `team-delivery-kit` em bloco durante S6.

### A6 — “Time autônomo” precisa de um limite operacional honesto

Há nove identidades disponíveis, mas papéis e fases determinam quais trabalham.
Isso é adequado; não precisamos de nove bots falando em toda atividade. Revisão
por outro perfil é independência de papel e evidência, não diversidade garantida
de raciocínio quando conta/modelo são os mesmos. Os gates externos continuam
necessários, sem adicionar obrigatoriamente outro modelo pago.

O materializador serializa pacotes: o próximo teste depende da integração
anterior. Dois slots não significam duas features em paralelo. Manter isso no
S6: a aprovação original previa começar serialmente. Paralelizar agora amplia
conflitos de baseline, merge e testes sem provar o fluxo básico.

Autonomia não significa capacidade de consertar qualquer defeito do próprio
controlador nem ausência de todo estado de espera. Uma falha sem recuperação
qualificada deve parar visivelmente com dono e próxima ação. Isso é preferível
a infinitos retries. O objetivo é eliminar esperas sem dono, dependências
impossíveis e necessidade de condução externa dos casos suportados.

Telegram real ainda não está conectado nesta fronteira. Outbox enfileirada não
é entrega recebida, nem existe prova de resposta humana retomando o fluxo pelo
canal. Fechar um único canal de controle por adaptação ao intake existente;
não restaurar nove gateways concorrentes como mecanismo de despacho.

## 4. Custo: onde vale atuar

Janela preservada de 140 chamadas após S4: 125 atribuídas por recibo ao S5 e
15 sem proveniência comprovada. Metadados do provedor, sem estimativas sobre
conversas ausentes; valores em dólares, não custo total de todo o projeto.

| Fase | Chamadas | Custo reportado |
|---|---:|---:|
| Brief e planejamento, incluindo revisão de plano | 3 | US$ 0,0061537 |
| Autoria de testes | 38 | US$ 0,1408407 |
| Revisão de testes | 22 | US$ 0,0882962 |
| Implementação | 19 | US$ 0,0841336 |
| Revisão de implementação | 7 | US$ 0,0369095 |
| Diagnóstico | 36 | US$ 0,0648189 |
| Sem atribuição comprovada | 15 | US$ 0,0633779 |
| Total da janela | 140 | US$ 0,4845305 |

Testes/revisão de testes e diagnóstico representam 96/125 chamadas atribuídas
(76,8%) e cerca de 69,8% do custo atribuído. Isso não demonstra desperdício de
todas essas chamadas; demonstra onde investigar retrabalho. Brief e planejamento
não são o principal centro de custo dessa amostra. O custo humano de intervenções
e espera provavelmente domina o problema, mas não foi medido financeiramente.

Prioridades de economia, em ordem:

1. **Eliminar tarefas impossíveis e instruções contraditórias.** É a maior
   oportunidade observada; não economizar retirando revisão ou regressão.
2. **Não reiniciar releases completas para investigar infraestrutura.** Usar
   fixtures locais estreitas; depois retomar o card e a evidência preservados.
3. **Reduzir contexto repetido.** A amostra inclui entradas de até 55.115 tokens
   em revisão de implementação. Examinar duplicação entre contexto inicial e
   `evidence()`; manter resumo referenciado e leitura sob demanda de recibos.
   Não eliminar testes/brief necessários à decisão para reduzir tokens.
4. **Limites de saída por fase, depois de medir.** Diagnósticos tiveram máximo
   de 2.926 tokens; revisões de implementação chegaram a 4.644. Autores chegaram
   a 12.602 (implementação) e 11.665 (testes). Não voltar a 8.192 para todos.
   Candidatos para avaliação posterior: 4.096 diagnóstico, 8.192 revisão e
   16.384 autoria. São hipóteses baseadas na amostra, não garantias. Reduzir o
   teto não reduz automaticamente o preço de uma resposta que já era curta.
5. **Verificar caching nativo.** Os 140 registros reportaram zero tokens de
   cache. Conferir suporte SDK/relay/provedor e prefixo estável antes de prometer
   economia; custos de escrita e mínimos variam. Não implementar cache de
   respostas/decisões nem alterar o modelo para obter cache. Referência:
   [OpenRouter, prompt caching](https://openrouter.ai/blog/tutorials/prompt-caching-sticky-routing/).

S6 consumiu duas chamadas de Produto, US$ 0,0046951 reportados. Contador
preservado: 6.953/7.064, restando 111 chamadas. Isso não garante conclusão dos
dois incrementos. Nenhum aumento de teto ou chamada foi feito nesta auditoria.
Não abrir um experimento pago separado de custo antes de resolver A1/A2.

## 5. Plano executável recomendado

### R1 — Alinhar contrato e capacidade, offline

Responsável: manutenção da plataforma, sem implementar o lobby pelos agentes.
Submeter F2/F3; preservar o aceite de negócio e as provas antigas. Em seguida:

- Definir manifesto de aceitação que liga critérios a casos reais da suíte e
  gates existentes. Critérios de regressão não exigem texto fictício na UI.
- Adaptar `browser.py`, os pontos de chamada em `quality.py`/`deployment.py` e
  os testes pertinentes para a mesma suíte congelada na prévia e no deploy.
  Conferir também os manifestos de cobertura, publicação e aceitação da release;
  trocar apenas a função de navegador não qualifica toda a cadeia.
- Qualificar com fixture mínima local: duas sessões independentes e uma terceira,
  leitura sincronizada, falha deliberada acima de três segundos, isolamento de
  dados, identidade errada, tentativa de rede externa e alteração do snapshot.
- Executar integralmente os testes antigos na fixture; evidência ausente,
  seleção parcial e aprovação obsoleta continuam falhando. Nenhum mutante precisa
  derrubar testes auxiliares alheios ao comportamento, conforme ADR 0003.
- Declarar explicitamente os limites do reparo técnico sob o novo formato.
  Não converter recibos JSON antigos nem dar autorização geral para editar testes.
- Publicar a alteração e criar novo export/bundle antes do primeiro Red S6.
  Manter o mesmo board/brief; mudanças de fingerprint exigem a migração existente
  ou proposta explícita, nunca editar banco ou transplantar aprovação.

**Saída:** a mesma suíte real passa nos dois alvos e recusa a fixture incorreta;
as capacidades ficam explícitas na admissão e no contexto do planejador/revisor,
que conferem a compatibilidade antes de despachar implementação paga. Não tentar
deduzir automaticamente toda a semântica de um brief em linguagem natural.
Não criar linguagem de testes, parser de semântica universal, novo banco ou serviço.
Se o reparo exigir isso, interromper o desenho e reconsiderar o escopo técnico.

### R2 — Consolidar o mínimo operacional público

Reusar `prepare_hermes_project.py`, `run_hermes_runtime.py`, Compose e locks
existentes. Transformar apenas os passos privados indispensáveis em entrada
pública ou instruções reproduzíveis. Não criar um instalador universal.

- Documentar/provar inicialização de credenciais/medidor em raiz nova e recusa
  de sobrescrever contador existente, sem publicar chave ou herdar conta do autor.
- Expor pausa, drenagem e parada econômica completas, com verificação de dono,
  processos e política. Manter volumes e homologação.
- Usar supervisão padrão na plataforma qualificada; reinício preserva pausa e
  não duplica efeito. Falha de configuração deve ficar visível, sem hot loop.
- Reproduzir a operação usando somente arquivos públicos e parâmetros privados
  documentados. Não copiar mais estado histórico para “fazer passar”.

**Saída:** outro operador consegue repetir os passos na plataforma declarada;
status diferencia parado/pausado/bloqueado/em execução. Não exigir suporte
multiplataforma nem um painel novo antes do S6.

### R3 — Executar o S6 existente, uma vez, com fronteira congelada

Após autorização de retomada, aplicar o aceite preservado ao brief correspondente
e registrar a harmonização F3 sem mudar requisitos. Conferir recursos próprios,
capacidade, orçamento e ausência de efeitos pendentes. Retirar somente testes
obsoletos comprovados segundo o contrato Docker; preservar `toso-*` e terceiros.

Produto/Lead/CTO devem gerar o plano; agentes devem produzir testes e produto.
O operador não escreverá a solução do lobby nem guiará cada handoff. Manter os
dois incrementos aprovados, serializados, revisão independente, PR/CI local,
deploy e QA sobre SHA exato. Diagnósticos usam os caminhos já qualificados.

**Saída:** dois incrementos entregues, regressão preservada e prova entre sessões
no deploy; registrar todas as intervenções. Se for preciso corrigir a plataforma,
a execução passa a assistida, preserva valor e continua recuperável. Não renomear
um ciclo, zerar board ou iniciar outro brief para apagar essa classificação.

O S6 já recebeu intervenção no refinamento do brief. Reparos da plataforma após
o aceite humano também devem constar no histórico, mesmo que o aceite ainda não
tenha sido aplicado ao intake. Uma execução técnica limpa após congelar essa
base pode qualificar essa fronteira, mas não torna todo o S6 retrospectivamente
autônomo desde o primeiro briefing. Pausa solicitada pelo proprietário e reparo
técnico do operador são eventos distintos, ambos registrados.

### R4 — Fechar distribuição e canal, sem outro produto de teste

Usar a mesma entrega para provar comunicação real de pergunta/resposta/URL,
indisponibilidade temporária do canal, restart/restore e rollback operacional.
Não injetar todas as falhas simultaneamente na entrega; provas operacionais
programadas continuam identificadas como tais.

Concluir o runbook e retirar serviços/arquivos legados do caminho padrão,
preservando recuperação. Separar auxiliares ainda usados antes de mover fontes.
Antes de muitas versões, acrescentar leitura de decisões canônicas de Git e
qualificar retenção de decisão antiga sem herdar autoridade de aprovação.

**Saída:** instalação reproduzível, entrega no outro repositório e comunicação
de resultado ao proprietário. Somente então retomar Truco completo e ampliar
stack, paralelismo ou papéis de observabilidade de produto.

## 6. Como avaliar avanço sem inflar percentuais

Não derivar autonomia de linhas implementadas, testes verdes ou número de bots.
Publicar uma tabela por release com: escopo/capacidade fixados, resultado,
intervenções técnicas externas após aceite, incidentes e recuperações internas,
tempo bloqueado com/sem dono, custo conhecido/desconhecido e regressões.

Hoje existe uma entrega técnica limpa delimitada (S4), uma continuidade assistida
(S5) e preparação S6. São casos diferentes; não há amostra comparável suficiente
para estimar probabilidade de entrega autônoma ou afirmar “90% pronto”. Depois
de uma entrega S6 limpa, provar continuidade sem intervenção no mesmo caminho,
sem apagar falhas anteriores. Autonomia será declarada para aquela stack e
escopo, não para qualquer projeto GitHub.

O critério para simplificar uma mudança é concreto: ela remove uma representação,
uma passagem manual ou uma dependência, mantendo a prova de qualidade? Se apenas
acrescenta uma recuperação para contornar um contrato contraditório, corrigir o
contrato primeiro. O caminho está correto; a próxima evolução deve tornar o
trabalho representável e executável, não aumentar a quantidade de mecanismos.
