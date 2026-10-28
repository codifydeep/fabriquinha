# ADR 0007 — Sucessão técnica e revisão de candidatos

Estado: **direção e refinamentos aprovados pelo proprietário em 28/10/2026**,
na resposta à auditoria de 28/10. Implementação e qualificação ainda pendentes.
Manter o modelo atual, sem fallback. Não ampliar o orçamento de chamadas.

## Autoridade e limites

A aprovação permite implementar P0–P6 da auditoria, incluindo revisão controlada
de testes candidatos. Não aprova automaticamente nenhum teste, implementação ou
entrega S6. O contrato instalado continua vigente até migração explícita.

A baseline já integrada permanece protegida. Candidatos não publicados podem
receber uma nova revisão justificada pelo brief, com diff completo, revisor
independente, Red apropriado, controles e todos os gates posteriores. O snapshot
anterior nunca é alterado. Remover cobertura ou mudar negócio continua exigindo
aceite específico do CEO. O comparador estrutural pode informar a revisão;
sua flexibilização não concede ao implementador acesso de escrita aos testes.

A política de console não é alterada por este aceite: a auditoria a identificou
como decisão separada, sem recomendar dispensa automática no caso atual.

## Operação comum de sucessão

Reusar cards nativos, recibos e journal existentes. Uma sucessão deve referenciar:

- Projeto, release, card, execução, fase e contrato de origem exatos.
- Incidente e última decisão técnica preservados.
- Evidência nova verificável e sua diferença em relação à tentativa anterior.
- Escopo da ação e responsável; revisão independente quando há mudança de candidato.
- Identidade idempotente e vínculo entre origem histórica e sucessora atual.

Não modificar counters nem reabrir diretamente um card triado. Evidência nova
não é simplesmente outro texto, prompt ou número de protocolo. Não admitir
sucessão enquanto houver lease ou efeito pendente. Uma tentativa duplicada deve
recuperar a mesma sucessora, inclusive após interrupção entre gravações.

A sucessão retoma a fase apropriada: reavaliar um parecer não é congelar testes;
congelar testes não é aprovar implementação. Nenhuma evidência histórica negativa
será convertida em positiva. O diagnóstico deve distinguir fato observado,
hipótese ainda não alcançada e operação realmente disponível.

## Ordem de implementação

1. P0: consolidar contexto atual e autorização; manter serviços sem despacho.
2. P1: qualificar sucessão de revisão em triagem com evidência nova e revisão
   nativa; reutilizar a substituição existente, evitando outra família de protocolos.
3. P2: aplicar autoridade de revisão ao candidato, preservando baseline e
   evidências históricas, sem ampliar escrita do implementador.
4. P3: testes de reinício, identidade obsoleta, duplicação, falta de evidência,
   autorrevisão e enfraquecimento; depois avaliação semântica delimitada.
5. Instalar sob manutenção e retomar S6 somente após essas provas offline.

Critério: a equipe consegue produzir uma próxima ação válida a partir de nova
informação sem alterar o controlador para cada incidente. Troca de modelo,
outro serviço, novo banco e recomeço do produto ficam fora deste trabalho.

## Implementação em andamento

A admissão comum `held_incident` substitui a duplicação no reparo de submissão.
A preparação `review_failure` vincula uma revisão triada ao handoff imutável do
seu autor; não usa o workspace mutável como evidência. Confere projeto, release,
card, contrato, autoria, snapshot e diagnóstico CTO. Ambas são verificações de
procedência: ainda não criam sucessora nem concedem aprovação ou escrita.

Próxima fronteira: proposta nativa com evidência nova e materialização idempotente
da sucessora. O despacho S6 permanece desabilitado até a qualificação dessa cadeia.

A preparação da proposta de revisão agora existe como operação não ativada:
exige relatório novo vinculado ao job exato e cria um card inicialmente bloqueado.
Texto de hipótese diferente não basta. A deduplicação usa origem/execução e
identidade da observação, não um contador novo de protocolo. Faltam qualificação
nativa de criação/reinício, revisão da proposta e materialização da sucessora;
nenhuma dessas capacidades é declarada instalada ou operacional por este código.
