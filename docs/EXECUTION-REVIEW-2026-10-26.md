# Revisão crítica da execução — 26 de outubro de 2026

**Estado da auditoria: proposta apresentada durante a pausa.**
O proprietário aprovou posteriormente os refinamentos e a retomada em 26/10;
consulte o [ADR 0004](ADR-0004-SCOPED-REPAIR.md) e o [status atual](STATUS.md).
O texto abaixo preserva a análise e a situação observada antes desse aceite.
Esta análise não autoriza ensaio, alteração de gate, correção dos testes congelados
ou aprovação retroativa. Revisão do código em `c9144c68`, documentos e recibos
privados preservados. Foram feitas leituras locais e consulta à documentação
pública da OpenRouter; nenhum modelo da equipe foi chamado nesta auditoria.

Referências: [estratégia aprovada](SIMPLIFICATION-REVIEW-2026-10-24.md),
[auditoria anterior](EXECUTION-REVIEW-2026-10-25.md),
[F1 aprovado](ADR-0003-BEHAVIOR-CONTROL-TARGETS.md),
[correções A/B e proposta C](POST-QA-REWORK-2026-10-26.md).

## 1. Parecer

**Manter Hermes + Kanban. A direção está correta; a execução precisa reduzir
o escopo do retrabalho e o custo de cada aprendizado.** O caminho novo chegou
a PR, CI, merge, implantação e rollback reais. Isso é progresso concreto sobre
os ensaios que paravam antes da implementação. Não há, porém, release autônoma
homologada nesse caminho. Não é correto converter quantidade de testes internos
ou porcentagem de etapas atravessadas em porcentagem de autonomia confiável.

A execução tem sido cuidadosa com evidências, independência, isolamento e
preservação das falhas. O problema principal agora é outro: o contrato trata
situações normais de manutenção como exceções difíceis, enquanto cada incidente
estimula um novo ensaio completo e mais código de coordenação. Estamos construindo
uma boa capacidade de recusar entregas; ainda falta uma capacidade igualmente
simples de corrigir e concluir a mesma entrega.

Não recomendo voltar ao Multica, introduzir Temporal, trocar modelo ou ampliar
papéis neste momento. Nada nos registros recentes demonstra que isso resolva
as contradições de contrato encontradas. Também não recomendo remover revisão,
Red, testes de regressão ou QA para produzir uma homologação artificial.

## 2. Evolução comprovada e limites

| Etapa do plano | Situação verificada | O que falta |
|---|---|---|
| S0/S1: referência e integração nativa | Concluídas no escopo qualificado; Hermes fixado, sem patches upstream | Preservar essa fronteira |
| S2: qualidade e execução | Red/freeze, Green, controles negativos e revisão exercitados; A/B mais recentes passaram em prova isolada | Contrato de correção de regressão e de teste tecnicamente errado |
| S3: publicação e implantação | PRs reais, CI local no SHA, merge, deploy e rollback atravessados | Fechar o ciclo com QA aprovado no mesmo commit |
| S4: entrega pela equipe | Última tentativa chegou à implantação; QA recusado e triagem preservada | Primeira homologação sem intervenção técnica externa |
| S5: continuidade | Vários mecanismos têm provas determinísticas | Segunda versão, memória entre perfis e recuperação real até homologação |
| S6: distribuição | Código público e preparação parcial | Instalação limpa e entrega em outro projeto sem estado privado herdado |
| S7: Truco | Não retomado por este caminho qualificado | Só depois dos marcos anteriores |

O PR [56](https://github.com/codifydeep/descartavel2/pull/56) integrou o commit
`b9f5d55fd4c5bef8061d04cf718a8b83336a3679`. Os dois jobs de QA implantado
falharam na mesma comparação. O CTO executou um experimento unittest verde e
retomou o QA; isso não eliminava a divergência do navegador. A triagem foi
correta ao impedir a repetição indefinida e não homologar.

As correções A/B posteriores propagam o erro real e executam o mesmo interpretador
de QA antes do merge. Foram qualificadas com 285 testes do núcleo e sete jobs
Docker/Chromium. Esses números descrevem a evidência anterior, não testes
reexecutados nesta auditoria. Não demonstram que os agentes já recuperam o caso.

Nos quatro últimos ensaios fechados analisados: **143 chamadas e zero
homologações autônomas**. A amostra é pequena e heterogênea: serve como diagnóstico
de desperdício e lacunas, não como estimativa estatística de confiabilidade.

## 3. Achados prioritários

### A1 — A última falha é primeiro uma divergência de contrato

O brief aprovado afirma que a saudação deve conter o nome aparado e que a equipe
pode escolher a redação. O teste Python usa `assertIn('Ana', greeting)`. O arquivo
QA usa `text: "Ana"`, interpretado como igualdade do texto completo. O produto
mostra `Hello, Ana! Welcome.`. Esse resultado satisfaz o trecho citado do brief,
mas não a comparação congelada. O segundo check também exige uma mensagem exata,
enquanto o brief deixa a redação do erro para a equipe.

Isso **não prova que todo o produto está correto**, nem autoriza ignorar o QA.
Prova que não devemos classificar automaticamente esta recusa como defeito do
produto. A revisão independente deixou passar duas especificações divergentes.
A/B antecipam a detecção, mas não resolvem qual especificação deve prevalecer.

**Proposta:** tornar explícita a ordem de autoridade: brief aprovado → decisão
técnica revisada → testes derivados. QA e Lead devem classificar o erro antes de
mandá-lo ao implementador. Corrigir um teste tecnicamente incorreto requer uma
nova revisão preservada, justificativa vinculada ao brief e revisão independente;
nunca editar silenciosamente o snapshot antigo. Não mudar globalmente `text`
para substring. Um operador novo, se necessário, deve ter semântica explícita.

Essa delegação de correções técnicas de testes altera o contrato atual e exige
aceite do proprietário. Exceções que removam cobertura ou mudem comportamento
de negócio continuam com o CEO. O caso presente pode ser o primeiro exemplo
restrito; não precisamos construir uma política universal de alterações de testes.

### A2 — O Red atual não comporta uma regressão já detectada

[`quality.py`](../src/fabriquinha/quality.py), método `red`, exige baseline verde
e falhas somente em casos novos. [`publication.py`](../src/fabriquinha/publication.py)
também exige baseline verde na CI. Logo, um teste existente que já falha na base
impede iniciar o conserto pela mesma esteira. É uma limitação encontrada por
inspeção do código; não foi a causa do último QA e não foi executado outro ensaio.

**Proposta de contrato, não aplicada:** distinguir dois tipos de Red:

- Funcionalidade nova: base verde e novo teste comportamental vermelho, como hoje.
- Regressão: teste existente falha no SHA defeituoso; revisor confirma a expectativa
  e o conjunto exato de falhas conhecidas. O autor corrige o produto; a suíte
  completa deve ficar verde, sem alteração dos testes protegidos. Acrescentar
  teste novo quando existe uma lacuna, não para duplicar artificialmente o que
  já demonstra o erro.

A CI de reparo deve reconhecer somente a falha de base previamente revisada,
recusar falhas adicionais e exigir a cabeça totalmente verde. Isso não é aceitar
um PR vermelho nem dispensar Red. A aprovação por SHA e os controles pertinentes
continuam obrigatórios. Não tornar essa ampliação pré-requisito para um reparo
que não precise dela; qualificá-la antes do cenário de regressão em S5.

### A3 — A proposta C é maior que a necessidade imediata

O código atual materializa um plano inicial em `seed.json` e `graph.json`;
recuperação oferece retomada, escalonamento ou bloqueio. Falta o caminho normal
de reparo pós-integração. A proposta C responde com gerações de todo o plano,
revisão CTO e substituição de cards. Isso pode ser necessário para mudança de
escopo, mas amplia muito a superfície para corrigir um pacote.

**Substituição proposta para C: pacote corretivo nativo, limitado.**

1. Incidente aponta para release, integração, SHA, relatório e pacote afetado.
2. Lead classifica: produto, teste/contrato, infraestrutura ou escopo. Infra não
   vira card de implementação por suposição; ambiguidade técnica vai ao CTO.
3. Criar apenas o pacote corretivo e suas dependências afetadas no Kanban.
   Mesmos brief e release; base atual; novo PR e novas evidências.
4. Preservar cards e recibos anteriores. Registrar qual pacote o reparo substitui
   para aceitação, sem transformar o resultado antigo em sucesso. Detectar ciclos
   e impedir duas correções concorrentes da mesma integração.
5. Suspender somente trabalho que dependa da base afetada. Não paralisar ou
   recriar tarefas independentes por conveniência do controlador.
6. A aceitação final resolve as substituições e verifica cobertura integral do
   brief, regressões, CI, implantação e QA no commit final.

O estado e os vínculos ficam no Kanban; snapshots e recibos continuam no Store.
Não criar um banco de workflow, um supervisor adicional ou outro serviço. Caso
o schema nativo não permita representar o vínculo com clareza, demonstrar essa
limitação antes de acrescentar uma nova máquina de estados.

### A4 — O contrato de validação muda junto com o checkout do controlador

`executor.preview_drivers` calcula hashes dos arquivos atuais `browser.py` e
`suite.py`; `quality.preview_evidence` e a observação da CI exigem esses hashes
atuais. Isso impede usar prova antiga como se satisfizesse um gate novo, o que
é correto. Porém, até alteração editorial nesses arquivos muda a identidade
exigida para evidências anteriores e favorece reinícios completos.

**Proposta:** um pequeno bundle imutável desses scripts, identificado e fixado
na execução. Separar versão do contrato de qualidade de versão operacional do
controlador. Correção do transporte não deve reinterpretar automaticamente uma
aprovação histórica. Mudança semântica ou correção de segurança exige revalidação
explícita do que afeta; nunca adaptar retroativamente o recibo antigo.
Usar o Store existente. Não construir registro de plugins ou migração genérica.

### A5 — Complexidade e documentação voltaram a crescer

A meta aprovada era cerca de 3.000 linhas próprias ativas e até 12 módulos.
O núcleo tem **5.779 linhas em 20 arquivos Python, incluindo `__init__.py`**;
os scripts somam 3.845 linhas e os testes Python 4.556. São categorias separadas:
fixtures e testes não devem ser contados como produção. O núcleo cresceu de
5.473 para 5.779 linhas entre `42ae3394` e `c9144c68`.

Ultrapassar a meta não torna o código errado. Mas exige a justificativa e a
reavaliação previstas no próprio plano. Manter a mesma meta no documento e
continuar acrescentando mecanismos sem discutir a expansão é execução incompleta
do plano. Não corrigir a métrica minificando ou movendo funções para scripts.

O roadmap misturava próximos passos já executados e instruções conflitantes:
reparar a mesma release e iniciar outra fronteira limpa. O setup ainda dizia
que a saída 16.384 aguardava aprovação, embora já autorizada e usada. Nesta
auditoria, essas referências foram alinhadas; documentos de ensaios antigos
continuam históricos. Próximas ações devem ter uma única lista vigente.

### A6 — Memória e papéis precisam de continuidade pequena, não outra plataforma

O adaptador usa `skip_context_files=True` e `skip_memory=True`, ferramentas
restritas por fase e contexto explícito do controlador. Portanto, instalar SOULs
ou skills no Hermes legado não comprova que as atividades do caminho novo os
consumam. Esse isolamento é útil, mas a memória corporativa entre versões ainda
precisa ser qualificada.

Recomendo manter decisões, interfaces e comandos de teste em poucos documentos
versionados no repositório do produto. O contexto deve carregar a lista desses
documentos no SHA correto, com leitura seletiva. Uma prova S5 deve trocar o perfil
e verificar que ele usa uma decisão anterior sem o operador reexplicá-la.
Sem banco vetorial, sumarizador periódico ou transcrições completas como memória.

Manter os nove papéis disponíveis, mas sem nove passagens obrigatórias. Produto
entra no brief; Lead responde pela entrega; CTO resolve arquitetura e impasses;
especialistas entram por demanda. Reviewer independente permanece obrigatório.
DevOps deve solicitar operações determinísticas, não conversar para consultar
status. Não criar agora papéis de SRE/agente auditor para observar outros agentes.
Instrumentação e insights de produto continuam uma expansão posterior.

## 4. Custos: o que sabemos e onde economizar

Totais das sessões nativas preservadas dos quatro ensaios mais recentes:

| Ensaio | Chamadas | Tokens de entrada | Tokens de saída |
|---|---:|---:|---:|
| output16k | 38 | 684.743 | 43.185 |
| networkpreflight | 31 | 552.938 | 25.920 |
| diagnostic-facts | 42 | 865.034 | 51.914 |
| hardening | 32 | 546.167 | 51.129 |
| Total | **143** | **2.648.882** | **172.148** |

Esses valores incluem contexto reenviado; não representam tamanho único do
projeto. São contadores do SDK, não reconciliação da fatura. Nas sessões lidas,
`actual_cost_usd` é nulo e o custo está `unknown`; o zero estimado não significa
gratuidade. O proxy preserva somente três totais de tokens, descartando detalhes
de custo/cache da resposta. Não é possível afirmar o gasto em dólares nem a
economia realizada com cache a partir desses registros.

Na última tentativa, 28.068 dos 51.129 tokens de saída são registrados como
raciocínio, aproximadamente 55%. Não somá-los novamente à saída. Isso recomenda
medição por fase; não justifica desativar raciocínio sem comparar qualidade.

Prioridades de economia, em ordem:

1. **Evitar recomeçar a release para testar uma correção de infraestrutura.**
   Completar uma recuperação assistida, declarada como tal; depois executar uma
   única qualificação limpa. Não importar a conclusão assistida como autonomia.
2. **Medir custo nas respostas já recebidas.** Preservar em allowlist o ID da
   geração, custo reportado, cache e raciocínio, ligados a release/fase/tentativa.
   Sem guardar prompts nem criar serviço de billing. A documentação da
   [OpenRouter](https://openrouter.ai/docs/guides/guides/usage-accounting) descreve
   esses campos na resposta, sem consulta adicional por geração. Dados ausentes
   permanecem desconhecidos; um timeout continua consumindo a reserva até
   reconciliação, sem reenvio automático.
3. **Diminuir saídas volumosas.** Hoje os controles negativos pedem substituições
   completas de arquivos. Preferir edições pequenas com hash esperado e trecho
   inequívoco, aplicadas pelo executor numa cópia descartável. Mesmos testes,
   revisão e alvos; muda o transporte, não a exigência de matar o comportamento.
   Evitar elevar novamente a saída para contornar payloads desnecessários.
4. **Estabilizar prefixos e medir cache.** Contexto estável primeiro, fatos da
   atividade depois. Qualificar compatibilidade do provedor antes de ativar
   marcações. A documentação de
   [prompt caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching)
   descreve campos de cache e comportamentos por provedor; nenhum percentual de
   economia está comprovado nesta instalação. Cache não substitui memória.
5. **Evitar computação idêntica repetida por retomadas.** Há sete jobs `integrated`
   sobre o mesmo snapshot e imagem na última tentativa. Alguns pertencem a fases
   e autoridades distintas; não são todos descartáveis. Avaliar reutilização
   apenas do cálculo determinístico com chave completa: snapshot, testes,
   bundle, comando e ambiente. A nova fase registra sua própria vinculação;
   revisão independente, SHA de CI, health e QA implantado não são dispensados.
   Não construir esse cache antes de fechar o reparo mínimo.
6. **Só depois comparar modelos/caps por papel.** Fixar a tarefa e medir custo
   por entrega correta, incluindo retries. Modelo mais barato por token pode
   custar mais por release. Não introduzir fallback silencioso.

O teto de chamadas protege quantidade, não valor monetário. Depois de medir,
acrescentar orçamento por release e aviso antecipado, com reserva conservadora
e tabela de preços identificada; não inventar custo quando o provedor não o
reporta. Não precisa de uma nova plataforma de observabilidade para isso.

O tempo do operador e a repetição de ensaios provavelmente são custos relevantes,
mas não foram cronometrados. Não atribuir valor ou economia percentual fictícios.
Serviços legados ociosos podem consumir memória/disco, não tarifa de nuvem;
sua parada definitiva pertence ao corte S6, com dados recuperáveis e sem tocar
projetos alheios. Esta auditoria não iniciou limpeza nem alterou containers.

## 5. Plano de execução recomendado ao Sol

As etapas abaixo são uma proposta de revisão, não autorização para retomar.
Implementar mudanças coesas e provas focadas; não criar um ensaio completo a
cada ajuste de log, prompt ou tratamento de erro.

| Ordem | Entrega concreta | Verificação de saída |
|---|---|---|
| P0 — decidir contratos | Aceite restrito de correção técnica de teste; C reduzido a pacote corretivo; regra separada para Red de regressão | Documento curto com autoridade, limites e exemplos; nenhuma evidência antiga reclassificada |
| P1 — fechar o reparo mínimo | Erro completo → classificação Lead/QA → revisão independente da correção → novo pacote/PR → CI/deploy/QA | Fixture reproduz o caso exato; reinício não duplica reparo; revisão antiga e entrega falha não são aceitas |
| P2 — fixar evidência e medir | Bundle imutável; métricas de custo permitidas nos recibos existentes; estado/resultado do ensaio derivados de uma referência única | Troca operacional não muda contrato silenciosamente; ausência de custo é `unknown`; zero chamadas na qualificação offline |
| P3 — recuperação real assistida | Continuar o caso preservado, se tecnicamente compatível, usando agentes para diagnosticar e corrigir | Homologação com novo SHA e todas as provas; explicitamente assistida, sem alegar S4 aprovado |
| P4 — S4 limpo | Uma entrega pequena completa com contrato e runtime fixados | Aprovação do brief → homologação sem operador conduzir etapas ou reparar runtime |
| P5 — S5 limitado | Segunda mudança, dois cards dependentes, outro perfil, regressão e um incidente recuperado | Testes anteriores preservados; memória usada; equipe chega à homologação após a falha |
| P6 — S6 e corte | Instalação do Git em outro diretório/repo; comandos operacionais claros | Sem sessões/UUIDs/imagens históricas obrigatórios; retirar legado ativo com recuperação preservada |

P1 não inclui replanejamento geral, escalonamento multiempresa, múltiplas stacks
ou novo serviço. P2 não inclui dashboard financeiro, cache universal ou extração
automática de memória. Se o caso preservado não puder continuar sem transplantar
aprovações, declarar o impedimento e usar uma fixture assistida nova; não fabricar
continuidade. A compatibilidade deve ser verificada antes de consumir modelo.

O Red de regressão deve estar qualificado antes de P5; não bloquear P3/P4 com
essa ampliação caso a correção concreta não dependa dela. Correções técnicas de
teste exigem sempre nova revisão, mesmo que o revisor seja o mesmo papel habilitado.

### Condições para parar de expandir a plataforma

- Cada incidente deve terminar em uma correção do produto, do contrato ou do
  mecanismo; não automaticamente numa nova abstração.
- Duas falhas da mesma classe sem evidência nova: interromper as chamadas daquela
  ação e corrigir a causa offline. Manter responsável e próxima ação visíveis.
- Intervenção do operador desqualifica autonomia daquela execução; não elimina
  seu valor como integração assistida nem exige repetir todos os passos para
  investigar a próxima falha.
- Não confundir espera humana/financeira legítima com deadlock. Qualificar que
  esperas liberam slots e trabalho independente continua. Não prometer ausência
  universal de starvation; provar cenários de fila e recuperação com dois slots.
- Manter uma pequena tabela de exceções ao orçamento de complexidade, mostrando
  requisito e alternativa rejeitada. Remover duplicação antes de adicionar
  generalização. Não exigir refatoração cosmética antes do primeiro resultado.

## 6. Qualidade e segurança: limites que devem continuar honestos

Testes completos, proteção de regressão e revisão independente continuam centrais.
Mas um teste pode estar errado: imutabilidade preserva a evidência, não torna sua
semântica infalível. O contrato precisa preservar e substituir uma revisão errada
de forma explícita; proibir qualquer correção técnica indefinidamente não é TDD.

A execução da suíte e da prévia QA compartilha o processo Python no reporter.
Montar o arquivo confiável somente leitura e resolver seu caminho explicitamente
evita a colisão de `browser.py` já tratada, mas não é prova de isolamento contra
alteração de estado Python pelos próprios testes. Esta é uma observação estática,
não um exploit demonstrado. Separar subprocessos e ambiente pode reduzir
contaminação acidental. Não anunciar atestação contra código deliberadamente
hostil nem construir uma plataforma adversarial antes da entrega mínima.

Reutilizar a mesma especificação de aceite entre pré e pós-deploy é desejável;
hoje Python e JSON duplicam expectativas. A/B reutilizam o interpretador JSON,
não eliminam essa duplicação. Após o primeiro ciclo, preferir testes de navegador
parametrizados por destino, mantendo IDs de aceite e revisão. Isso deve substituir
uma representação, não acrescentar uma terceira linguagem de contratos.

## 7. Medidas de sucesso

Publicar por execução: resultado, intervenção externa, release/SHA, critério não
coberto, chamadas/tokens/custo conhecido, tempo em execução/espera e responsável
pelo bloqueio. Não usar cards concluídos, quantidade de recibos, workers ativos
ou testes do controlador como substituto de entrega.

Uma homologação sem intervenção prova viabilidade. Uma segunda versão com
regressão e recuperação prova continuidade. Uma instalação limpa prova a
portabilidade delimitada. Só então ampliar para o Truco. Percentuais gerais
continuam estimativas subjetivas enquanto faltarem esses três marcos; esta
auditoria prefere informar explicitamente o que foi e o que não foi demonstrado.

**Decisão recomendada:** manter a arquitetura simplificada, reduzir C, permitir
correção técnica de testes com autoridade e evidência, medir custo e fechar uma
release. O objetivo não é deixar o controlador preparado para toda falha possível;
é demonstrar uma equipe que consegue reconhecer, corrigir e entregar um trabalho
pequeno pelo seu próprio processo, dentro de limites claros.
