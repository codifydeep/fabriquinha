# Balanço crítico e próximos passos — 31/10/2026

## Parecer e correção da comunicação

Manter Hermes + Kanban, o modelo atual e a arquitetura de um host. Há uma cadeia
real de entrega funcionando, mas sua repetibilidade sob evolução da plataforma
não está suficientemente demonstrada. Não recomeçar, trocar de orquestrador ou
construir uma nova recuperação para cada sintoma.

A auditoria de 30/10 registrou a v0.3 como um ciclo autônomo observado após o
aceite, incluindo recuperação técnica. Esse marco permanece válido no escopo
observado. A frase posterior de que ainda faltava qualquer ciclo autônomo foi
imprecisa. O que falta é repetibilidade; as entregas assistidas seguintes não
apagam a v0.3 nem se tornam autônomas por terminarem com sucesso.

O escopo comprovado continua sendo Python/HTTP, navegador, um host, GitHub,
memória temporária do produto e uma release ativa. Não equivale a qualquer SaaS,
3D/mobile, paralelismo amplo ou operação sem limites diante de serviços externos.

## Evidência atual

- Saída e reposição de jogadores: `HOMOLOGADA`, dois incrementos dependentes,
  PRs [19](https://github.com/codifydeep/descartavel/pull/19) e
  [20](https://github.com/codifydeep/descartavel/pull/20).
- Commit final `a731d2d6588d5c52121584d5cf8056c7074aea2d`; ambiente conferido na
  verificação anterior: http://127.0.0.1:62413, health 200 e identidade correta.
- Primeiro incremento: 38 testes. Segundo: 43, dos quais 41 no QA de navegador.
  CI obrigatória, revisão independente, rollout, rollback e QA registrados.
- Comparação nesta auditoria: todos os 15 arquivos de testes/manifestos do
  baseline preservados byte a byte; quatro arquivos adicionados.
- Ciclo explicitamente assistido no recibo final: houve reparos de capacidade,
  diagnóstico e leitura histórica durante sua execução.
- Após a última instalação, o fluxo completou pedido de mudanças na revisão,
  diagnóstico de handoff, timeout e retomada até homologação, sem nova intervenção
  operacional registrada nesta conversa. Isso comprova um trecho recuperável,
  não autonomia retroativa do ciclo inteiro.
- Nenhum worker ativo; controlador rodando, sem issues internas reportadas.
  Outbox sem fila pendente ou erro corrente, mas com uma ocorrência `uncertain`.
  Não presumir que esse evento foi entregue, nem atribuí-lo à última release sem
  verificar seu vínculo. É uma pendência operacional a classificar.
- Última suíte da automação: 541 testes. Não é porcentagem de autonomia.

## Situação do plano aprovado

| Item de 30/10 | Situação em 31/10 | O que ainda falta |
|---|---|---|
| P0: documentação corrente | Atualizada nesta auditoria | Evitar que relatos históricos voltem ao contexto como estado atual |
| P1: matriz de revisão | Redação alinhada à seleção executável | Monitorar promessas de sign-off que o grafo não representa |
| P1: fixtures | Reparo homologado, ciclo assistido | Manter controles semânticos; não reabrir o mesmo reparo |
| P1: Kanban | Orientação instalada | Resumo de release, saúde, responsável, último progresso e predecessores |
| P2: próxima entrega útil | Saída/reposição homologada; substituiu a proposta de motor do Truco | Segunda comprovação comparável sem reparo externo após aceite |
| P3: recuperação operacional | Provas isoladas e recuperações reais parciais | Interrupção em efeito externo e restauração operacional com reconciliação |
| P4: distribuição | Fonte pública, documentos, instalador e provas parciais | Outra pessoa instalar e entregar usando apenas o repositório |
| P5: ampliar produto | Lobby evoluiu | Motor do Truco; depois capacidades novas qualificadas separadamente |

No plano original S0–S7, S0/S1 têm evidências de viabilidade; S2/S3 operam em
entregas reais; S4/S5 têm evidências delimitadas de entrega, continuidade e
recuperação. S6 não deve ser chamado de distribuição reproduzível por terceiros
apenas porque existe uma instalação chamada S6. S7 permanece a expansão real do
Truco, ainda sem regras completas, experiência 3D ou mobile.

## Por que os bloqueios persistiram

1. **Premissas locais tratadas como universais.** O limite de 20 critérios de um
   brief foi aplicado à história inteira de regressões. O crescimento legítimo
   encontrou um limite artificial. Agora há limites cumulativos explícitos;
   ainda são limites de recurso, não permissão de remover testes ao atingi-los.
2. **Contexto diagnóstico incompleto.** A submissão rejeitada não acompanhava o
   incidente. O diagnóstico via um baseline verde posterior e perdia a causa.
   Recusa e candidato agora ficam preservados e distinguidos do estado corrente.
3. **Compatibilidade testada só parcialmente.** A atualização passou por testes
   unitários e retomada de cards, mas falhou na leitura da homologação antiga
   durante rollback. Faltava validar o consumidor seguinte da evidência.
4. **Acoplamento entre história e autoridade atual.** Exigir o bundle corrente
   de um recibo histórico confundia leitura de proveniência com nova aprovação.
   A visão histórica agora é somente leitura; novos gates continuam estritos.
5. **Recuperar sem mudar a pré-condição.** Um diagnóstico verde do produto levou
   à repetição da integração sem corrigir sua incompatibilidade. A retomada
   deveria exigir evidência de que a causa concreta mudou, não só suite verde.
6. **Fragilidade de execução do modelo.** Handoffs ausentes, truncamento e timeout
   continuam ocorrendo. São diferentes de falhas da aplicação e não se resolvem
   sempre aumentando contexto, tokens ou retries.

Os controles de qualidade bloquearam corretamente resultados insuficientes.
O erro de engenharia foi deixar combinações importantes fora do preflight e
instalar correções estreitas demais. Responsabilidade da plataforma não deve
ser transferida ao CTO de produto como se ele pudesse modificar seus gates.

## Avaliação crítica do desenho

Pontos fortes: handoffs persistentes, snapshots imutáveis, revisão independente,
TDD real, regressões preservadas, PR/CI no SHA exato, QA implantado, rollback,
contabilidade delimitada e classificação assistida. Manter essas propriedades.

Dívida: 10.773 linhas Python em `src/fabriquinha`, contra aproximadamente 9,7 mil
na auditoria anterior e meta inicial de cerca de 3 mil. A contagem inclui código
que pode ter graus diferentes de uso; não é, isoladamente, uma medida de risco.
Contudo, a meta de simplicidade não foi atingida. Muitos caminhos de manutenção,
reparo, sucessão e compatibilidade já exigem conhecimento especializado.

Não fazer uma reescrita para atingir uma contagem. Mapear caminhos realmente
usados, cobri-los com provas de caracterização e extrair apenas regras comuns
já demonstradas: admissão, vínculo de evidência, identidade da execução, sucessão
idempotente e fechamento. Remover um ramo somente com prova de que nenhum estado
retido depende dele. Separar migrações operadas pelo mantenedor da recuperação
normal do time. Não transformar a recuperação em autorização para agentes
alterarem sua própria governança.

## TDD, papéis e memória

A preservação dos 15 arquivos e o crescimento de 30 para 43 casos sustentam a
continuidade. Não provam cobertura completa do negócio. Revisão semântica e
controles negativos relevantes continuam essenciais; contar assertions não basta.
Preservar a sequência Red, freeze independente, Green, controles e revisão.

Não adicionar papéis agora. Produto especifica e pergunta ao CEO sobre negócio;
Lead organiza; CTO decide técnica; QA produz e verifica testes; implementador
entrega; DevOps integra. Independência é lógica por perfil nesta PoC de uma conta
GitHub, não independência organizacional forte. Ativar Designer/Mobile/Dados
apenas quando a demanda exigir.

A memória artefactual funcionou entre incrementos, mas a compatibilidade temporal
falhou. Versionar claramente: decisão vigente, decisão substituída e evidência
histórica. Contexto de atividade deve conter brief aplicável, baseline, plano,
última recusa e próxima operação permitida. Evitar retransmitir narrativas antigas.
Não há evidência que justifique banco vetorial ou novo serviço de memória agora.

## Prontidão estimada — mesma régua, sem falsa precisão

| Dimensão | Peso | Estimativa |
|---|---:|---:|
| Cadeia de entrega | 20% | 95% |
| TDD, regressão e revisão | 20% | 92% |
| Recuperação autônoma | 25% | 75% |
| Continuidade e memória | 15% | 88% |
| Canal e comunicação | 10% | 85% |
| Operação e distribuição | 10% | 60% |

Média ponderada aproximada: 84%; comunicar 80–85% no escopo restrito. Estimativa
subjetiva de prontidão, com incerteza de cerca de dez pontos; não mede esforço
restante, probabilidade de sucesso ou conclusão do Truco. O volume de correções
não justifica elevar para 95%. Não atribuir um único percentual ao objetivo mais
amplo de qualquer software em qualquer stack.

## Custo

Manter o modelo. O relatório consultado cobre 828 chamadas com custo reportado
somando US$ 4,9314150, e informa lacunas históricas de contabilização. Esses números
não são o custo total do projeto nem o custo desta release. Não atribuir custo zero
quando não houver associação recuperada por release. A contabilidade consultada
vai até a chamada 7.779; teto instalado 8.500 deve ser reconferido antes de outro ciclo.

Economia prioritária: não repetir diagnósticos verdes que não testam a causa;
trabalhar com arquivos e contexto delimitados; orientar gravações menores para
reduzir truncamento; separar retries técnicos de novas tentativas de raciocínio;
reutilizar jobs apenas com identidade completa idêntica. CI integrado, controles
negativos e QA implantado têm funções distintas e não devem ser removidos como
suposta duplicação. Medir custo por entrega aceita e por recuperação, incluindo
intervenções humanas; não apenas custo por token. Não aumentar limites por padrão.

## Próximos passos propostos

### A — Fechar operação e visão corrente antes do próximo brief

Mantenedor: adicionar resumo somente leitura ao painel existente, derivado do
grafo vigente e recibos. Exibir release, classificação assistida/autônoma observada,
URL/SHA, card ativo, dono, último progresso, impedimento e próxima ação. Separar
saúde do dispatcher de progresso do trabalho. Histórico permanece acessível;
predecessores não viram `done` artificialmente. Estado antigo vira desconhecido.
Classificar o aviso de envio incerto sem reenvio cego ou confirmação fictícia.
Saída: usuário identifica avanço ou bloqueio sem logs/SQL, e painel não modifica
estado. Sem serviço ou banco novo. Não expandir para analytics de produto agora.

### B — Consolidar compatibilidade, sem novo protocolo de coordenação

Mantenedor: uma prova parametrizada com duas gerações de validador e duas releases:
leitura do histórico, Red/freeze atuais, publicação, CI, seleção de rollback,
implantação, QA e fechamento. Rejeitar bundle estrangeiro, SHA divergente, revisão
obsoleta e evidência antiga usada como nova. Testar interrupção na migração e
retomada idempotente. Separar prova offline de integração real; ambas devem ser
nomeadas. Estender as provas existentes, não construir outro harness.
Saída: mudança de bundle não quebra seus consumidores seguintes e não amplia
permissões de evidências antigas. Refatoração só se remover duplicação coberta.

### C — Entrega útil do Truco para repetir a autonomia

Produto propõe o primeiro escopo pequeno do motor determinístico de regras,
exposto numa experiência web verificável, em dois incrementos dependentes. O time
propõe a decomposição e o CEO aprova regras/escopo; não presumir variante detalhada
nem aprovar brief por este documento. Evitar mais features de lobby cuja única
justificativa seja testar a fábrica. Manter stack qualificada, sem 3D/mobile agora.

Antes do aceite: preflight completo, baseline/rollback recuperáveis, budget real
suficiente, fonte/configuração fixadas e classificação prevista. Após o aceite:
sem operador alterar plataforma, cards, testes ou workspaces. Falha recuperável
segue o fluxo; falha da plataforma fica atribuída ao mantenedor e reclassifica o
ciclo antes de qualquer intervenção. Preservar artefatos para retomar a entrega.
Saída: outra entrega comparável integral sem intervenção. Proposta de política:
duas entregas consecutivas assim sustentam repetibilidade inicial, sem prometer
uma taxa estatística de sucesso ou exigir ensaios indefinidos.

### D — Recuperação operacional e distribuição

Em cópia isolada, interromper o supervisor durante um efeito externo escolhido,
verificar ausência de PR/merge/deploy duplicados e preservação do consumo. Restaurar
backup completo, validar vínculos Git/artefatos/ledger e reconciliar. Não ativar
segunda instância escritora sobre o projeto real. Depois instalar fonte congelada
em outro ambiente/repositório seguindo só README; idealmente outro operador.
Saída: entrega pequena, pausa/retomada e recuperação sem conhecimento privado.
Não confundir SQLite íntegro ou restore sintético com recuperação operacional.

### E — Expandir por capacidade

Após a repetibilidade inicial, desenvolver o Truco e qualificar persistência,
frontend/3D e mobile separadamente. Observabilidade de produto entra por pergunta
concreta e critérios de instrumentação, não por novos bots sem trabalho definido.
Não bloquear todo desenvolvimento útil até concluir distribuição pública perfeita.

## Limites desta auditoria

Leitura de documentos, fonte, board e recibos; sem novo ciclo pago, mudança de
modelo, gates, cards ou produto. A auditoria não aprova novo brief. Publicação
apenas de documentação corrente. As auditorias anteriores permanecem históricas.
