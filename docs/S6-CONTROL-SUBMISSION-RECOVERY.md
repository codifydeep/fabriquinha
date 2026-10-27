# S6 — submissão de controles e recuperação limitada

Estado: correção de orientação validada offline; instalação e continuação após
triagem ainda pendentes. Não é aprovação de entrega nem autorização para reset.

## Evidência e causa

A equipe executou Red, revisão independente, freeze e Green. Duas atividades de
implementação terminaram em texto, sem operação terminal válida, após recusas
parciais de controles negativos. O Lead fez um experimento e retomou; a repetição
chegou ao CTO e permaneceu em hold. Os gates funcionaram, mas a recuperação não
levou à entrega. Suíte funcional verde não resolve cobertura negativa ausente.

O feedback dizia corrigir os alvos faltantes, sem explicitar que cada submissão
precisa reenviar o conjunto completo. As propostas seguintes substituíam o
conjunto anterior por outro parcial. A cobertura é unida entre mutações da mesma
chamada; chamadas recusadas não acumulam autoridade. O diagnóstico enfatizou o
Green, embora os fatos da recusa negativa estivessem disponíveis.

## Reparo mínimo já implementado em fonte

- Uma orientação compartilhada no tool schema, na recusa e no diagnóstico:
  reenviar todas as mutações úteis juntas; cada uma parte do mesmo snapshot Green.
- Formato explícito: caminho de produto para conteúdo completo substituto;
  nenhuma alteração de teste, configuração ou produto real para simular mutante.
- Experimento Green diagnostica o produto; não comprova os controles negativos.
- Regressão prova que duas submissões parciais continuam recusadas, enquanto o
  conjunto completo satisfaz os mesmos alvos. 402 testes passaram.

Não houve mudança nos alvos, cálculo de cobertura, limites de mutações ou gates.
A fonte instalada e as evidências congeladas continuam preservadas.

## Próxima fronteira — continuação técnica após triagem

Antes de retomar o produto, qualificar uma continuação limitada pela equipe:

1. Reusar a revisão técnica e o mecanismo existente de correção, sem novo daemon
   ou banco. A correção deve distinguir defeito do protocolo de defeito do produto.
2. Preservar triagem e contadores do card anterior. Não reabrir o mesmo card nem
   limpar o breaker. Uma eventual substituição precisa de vínculo explícito,
   justificativa e revisão independente no mesmo grafo/release.
3. Reusar o snapshot e os testes congelados como entrada histórica, nunca como
   Green/controles aprovados da execução nova. Reexecutar os gates e a revisão.
4. Tornar a substituição recuperável e idempotente antes de liberar dependências.
   Recusar duplicação, troca de snapshot/testes e aprovação de revisão obsoleta.
5. O CTO deve produzir orientação sobre a recusa negativa; não basta repetir um
   experimento Green. Não pedir ao CEO uma decisão técnica nem gerar outro brief.
6. Qualificar offline antes de instalar. Somente então permitir que os agentes
   submetam uma nova entrega, conservando a falha como parte do resultado S6.

A admissão somente leitura (`submission_failure`) está implementada: vincula
triagem, execução, decisão/experimento do CTO, recusa negativa, snapshot e freeze
independente. Rejeita divergências e efeitos pendentes; não cria cards nem libera
o breaker. Os vínculos também foram conferidos nas evidências reais preservadas
do S6, sem chamadas ao modelo. A criação idempotente da proposta também está implementada em fonte, ainda
sem ligação ao despacho: somente Lead, classificação de submissão limitada,
revisão independente do CTO vinculada aos mesmos fatos e nenhuma alteração
do card em triagem. Classificações de infraestrutura/escopo continuam holds.
A substituição do trecho ainda não iniciado e a qualificação nativa ponta a ponta
permanecem pendentes. Testes de unidade dessa etapa não representam retomada real.
A orientação e a admissão isoladas não fecham essa lacuna de autonomia. A cota adicional aguarda autorização e não foi
aplicada; trabalho offline pode prosseguir sem chamadas ao modelo.
