# Roadmap vigente — 26 de outubro de 2026

**Retomada e refinamentos aprovados em 26/10/2026.** P1/P3 têm recuperação assistida homologada pelo PR 57.
P2 foi qualificado offline sob o [ADR 0005](ADR-0005-VALIDATION-AND-ACCOUNTING.md);
o próximo trabalho é P4/S4 limpo. A prova assistida não será reclassificada como autonomia.
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
homologação assistida. **S4 sem intervenção não está concluído.**
S5, S6 e S7 permanecem não qualificados.

## Próxima sequência proposta

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

**Saída:** uma homologação completa sem intervenção técnica externa. Não repetir
brief/planejamento a cada ajuste operacional apenas para investigar outra fase.

### P5 / S5 — Continuidade, regressão, memória e recuperação

Segunda versão na mesma aplicação, dois cards dependentes, outro perfil usando
uma decisão versionada e pelo menos uma falha recuperada pela própria equipe.
Qualificar o Red de regressão antes de usá-lo. Todos os testes anteriores continuam
protegidos e executados. Falhas de transporte/permissão podem usar fixtures
separadas; não exigem um ensaio pago completo por caso.

**Saída:** segunda homologação com regressão preservada e recuperação real.
Verificar slots livres durante espera e progresso de tarefa independente; uma
espera humana legítima não é promessa de ausência universal de starvation.

### P6 / S6 — Reutilização por terceiros e corte do legado

Instalar do Git em outro diretório/repo sem bancos, sessões ou UUIDs históricos.
Provar setup, doctor, start, pause, status, resume, upgrade/rollback e limpeza
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
