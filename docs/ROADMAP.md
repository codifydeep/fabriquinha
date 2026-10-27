# Roadmap vigente — 27 de outubro de 2026

**Pausa antes da implementação S6.** O CEO aprovou o brief; o aceite está
preservado e ainda não foi aplicado ao intake. A [auditoria de 27/10](EXECUTION-REVIEW-2026-10-27.md)
recomenda resolver a incompatibilidade do QA entre sessões e harmonizar a
autoridade técnica antes do despacho. R1–R4 naquele documento são a sequência
proposta, pendente de aceite dos refinamentos; não substituem silenciosamente
os contratos aprovados nem marcam S6 como qualificado.

**Retomada e refinamentos aprovados em 26/10/2026.** P1/P3 têm recuperação assistida homologada pelo PR 57. O PR 58 também chegou
à homologação assistida após recuperar um handoff e corrigir a regressão CI.
P2 foi qualificado sob o [ADR 0005](ADR-0005-VALIDATION-AND-ACCOUNTING.md).
P4/S4 chegou à primeira homologação técnica sem intervenção externa pelo PR 59;
veja o [escopo e as evidências](HERMES-S4-QUALIFICATION.md). O [S5](HERMES-S5-QUALIFICATION.md) chegou à homologação assistida; o próximo
trabalho é operação/portabilidade S6, sem repetir outro S4 genérico. Os ensaios assistidos não foram reclassificados.
As cotas e o modelo existentes continuam limitando o consumo.

A estratégia aprovada continua [Hermes + Kanban](SIMPLIFICATION-REVIEW-2026-10-24.md).
O [F1 aprovado](ADR-0003-BEHAVIOR-CONTROL-TARGETS.md) continua vigente. A
[auditoria de 26/10](EXECUTION-REVIEW-2026-10-26.md) propõe mudanças adicionais de
contrato e um reparo menor, agora aprovados explicitamente. A implementação inicial
é limitada pelo ADR 0004; funcionalidades posteriores não são consideradas prontas.
O [status](STATUS.md) registra o resultado real mais recente.

## O que já passou

- S0/S1: referência preservada e integração Hermes/Kanban qualificada, sem patches
  upstream. Multica/Temporal não participam do caminho novo.
- S2/S3: qualidade e operações determinísticas têm provas isoladas; modelos reais
  já atravessaram Red/freeze, Green, controles, revisão, PR/CI/merge e implantação.
- A/B do [plano pós-QA](POST-QA-REWORK-2026-10-26.md): erro real propagado e mesmo
  QA congelado executado antes do merge; 285 testes do núcleo e sete jobs reais
  Docker/Chromium qualificados. Zero chamadas pagas nessa prova específica.

O PR 56 foi implantado com rollback/restauração, mas o QA congelado falhou.
O PR 57 corrigiu a divergência por revisão técnica do contrato QA e chegou à
homologação assistida. O PR 59 qualificou o S4 técnico sem intervenção.
S5 entregou a segunda homologação, com assistência preservada. S6 e S7
permanecem não qualificados; autonomia geral não foi declarada.

## Marcos e sequência de execução

### P0 — Refinamento de contrato aceito

Aceite registrado no ADR 0004: autoridade para corrigir teste tecnicamente errado sem alterar o brief,
sempre com nova revisão independente e histórico preservado. Reservar ao CEO
mudanças de negócio e exceções que removam cobertura. Separar o futuro Red de
regressão já detectada do Red de funcionalidade nova.

A proposta substitui o replanejamento integral de C por um pacote corretivo
ligado à integração falha. Não aceitar implicitamente testes modificados nem
zerar triagem, breaker ou recibos. Detalhes e limites estão na auditoria.

### P1 — Implementar e qualificar o reparo mínimo

Usar o erro real para classificar produto, teste, infraestrutura ou escopo.
Criar somente o reparo e dependências afetadas, com base atual, revisão, novo PR,
CI e QA. Preservar o plano e os resultados anteriores como história, registrando
qual pacote é substituído para aceitação. Não criar outro banco ou serviço.

**Saída:** fixture do caso exato completa o reparo; reinício não duplica cards ou
PR; aprovação obsoleta, alteração silenciosa de teste e falso sucesso são recusados.
Não implementar replanejamento universal antes dessa prova.

### P2 — Estabilizar a evidência e medir custo

Fixar bundle imutável de validação por execução. Distinguir mudança operacional
do controlador de mudança semântica do gate; revalidar explicitamente o que for
afetado, sem reinterpretar recibos históricos. Registrar metadados de custo/cache
já retornados pelo provedor, sem prompts ou credenciais.

**Qualificado:** 306 testes do núcleo; treze jobs Docker/Chromium com scripts
fixados, inclusive após edição do checkout; nove atividades SDK e onze respostas
HTTP locais com atribuição, custo sintético, autenticação e pausa preservada.
A CI da fixture cobre funcionalidade nova com testes adicionados e correção QA
revisada. Zero chamadas pagas. Campos ausentes continuam desconhecidos. Cache universal,
novo dashboard e troca de modelo ficam fora.

### P3 — Fechar uma recuperação assistida

Após autorização de retomada, verificar se o caso preservado pode continuar sem
transplantar aprovações. A equipe deve diagnosticar e corrigir pelo novo caminho.
Se necessário, usar uma fixture assistida nova, com justificativa explícita.

**Saída:** novo SHA homologado com todas as provas, identificado como assistido.
Isso fecha a integração do mecanismo; não aprova S4 nem oculta intervenção.

### P4 / S4 — Uma entrega completa sem condução do operador

Contrato/runtime fixos, preparação e orçamento conferidos. Produto refina o brief;
CEO aprova uma vez; equipe conduz testes, revisão, implementação, PR, CI, deploy e
QA. O operador observa. Reparo externo invalida a qualificação de autonomia daquela
execução, mas não apaga seu valor como evidência assistida.

Qualificado antes do novo ciclo: comentários de diagnóstico referenciam somente
o recibo durável. A prova nativa recupera a orientação integral e a retomada após
reinício, enquanto PR genuíno continua guardado. Executar a próxima fronteira a
partir de uma exportação da revisão publicada, evitando imports do checkout mutável.

**Qualificado:** PR 59, nove testes, três mutações cobrindo seis alvos, CI no PR/merge, deploy,
rollback e QA. Os 27 arquivos exportados do runtime ficaram intactos; zero
reinícios/intervenções técnicas. O brief anterior foi reutilizado com autorização
condicional exata; isso não qualifica descoberta de produto nova.

**Saída:** uma homologação completa sem intervenção técnica externa. Não repetir
brief/planejamento a cada ajuste operacional apenas para investigar outra fase.

### P5 / S5 — Continuidade, regressão, memória e recuperação

Executar o [plano S5](S5-CONTINUITY-PLAN.md), preservando a entrega S4.

Segunda versão na mesma aplicação, dois cards dependentes, outro perfil usando
uma decisão versionada e pelo menos uma falha recuperada pela própria equipe.
Qualificar o Red de regressão antes de usá-lo. Todos os testes anteriores continuam
protegidos e executados. Falhas de transporte/permissão podem usar fixtures
separadas; não exigem um ensaio pago completo por caso.

**Resultado observado:** dois pacotes dependentes homologados, 29 testes,
memória entre perfis e recuperação real, com sete intervenções externas.
Ver [auditoria S5](HERMES-S5-QUALIFICATION.md); não equivale a ciclo limpo.

**Saída:** segunda homologação com regressão preservada e recuperação real.
Verificar slots livres durante espera e progresso de tarefa independente; uma
espera humana legítima não é promessa de ausência universal de starvation.

### P6 / S6 — Reutilização por terceiros e corte do legado

Executar o [plano S6](S6-PORTABILITY-PLAN.md), preservando as evidências S4/S5.
Antes do despacho, tratar os achados A1/A2 da auditoria de 27/10. Infraestrutura
pronta não demonstra que o executor consegue provar todos os critérios do brief.

Instalar do Git em outro diretório/repo sem bancos, sessões ou UUIDs históricos.
Corrigir e qualificar atribuição das chamadas auxiliares sem retroatribuir as
15 chamadas históricas. Provar setup, doctor, start, pause, status, resume, upgrade/rollback e limpeza
com propriedade qualificada. Declarar somente stacks e plataformas testadas.
Depois, retirar os serviços legados do caminho ativo preservando recuperação.

**Saída:** entrega reproduzível por instruções públicas. Só então iniciar S7,
a retomada do Truco e a ampliação gradual de papéis/observabilidade de produto.

## Regras de escopo

- Manter revisão independente, TDD, proteção de regressões e QA do commit implantado.
- Não criar outra infraestrutura de orquestração, memória ou observabilidade agora.
- Uma correção operacional não torna um resultado antigo válido sob outro contrato.
- Duas falhas equivalentes sem evidência nova suspendem aquela ação; não geram
  infinitas chamadas ou replanejamentos.
- O Red de regressão é necessário para S5; não deve bloquear o reparo atual se ele
  não depender dessa ampliação.
- Acompanhar entrega, intervenções e custo conhecido; não usar número de testes do
  controlador como medida de autonomia.

As sequências R0–R5 e instruções anteriores de iniciar novas fronteiras permanecem
no histórico Git e na auditoria de 25/10. Não são ordens concorrentes a esta lista.
