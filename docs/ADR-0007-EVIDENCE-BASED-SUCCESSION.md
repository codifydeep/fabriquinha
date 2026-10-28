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

### Prova nativa de persistência da proposta

`scripts/qualify_review_proposal.py` passou com Hermes upstream fixado, em raiz
isolada. Usou evidências de admissão programadas: qualifica a persistência nativa,
não a decisão semântica. Uma interrupção após criação e antes da confirmação foi
seguida de reconstrução com conexão/operação novas. A repetição recuperou o mesmo
card: zero duplicações, origem ainda triada, proposta bloqueada e claim recusado.
Zero chamadas ao modelo ou Docker; nenhuma aprovação de entrega.

A primeira tentativa foi recusada porque a fixture não declarou o workspace do
card de origem. A fixture foi corrigida e a falha preservada. Não houve redução
da verificação de contrato. Revisão da proposta, materialização da sucessora e
obtenção de evidência nova pela equipe continuam pendentes de qualificação.

O contrato da proposta passou a admitir `reassess`, `infrastructure` ou `scope`,
sempre sem caminhos de teste. A revisão independente revalida a origem e o job
da observação, e o contexto apresenta os dois relatórios. O SDK distingue esta
fase da correção de fixture e do reparo pós-deploy. Isso não habilita sucessora
nem escrita; a cadeia nativa completa e sua ativação continuam pendentes.

A prova nativa foi ampliada para o handoff Lead→CTO. A proposta exige o brief
aprovado da mesma release e o inclui como input; a fixture simula essa autoridade
sem reivindicar nova aprovação humana. Após a ativação explícita somente no
ensaio isolado, Lead submeteu e CTO revisou pelo Kanban nativo. Autorrevisão foi
recusada. A aprovação da proposta conservou `delivery_approval=false` e a origem
em triagem. A materialização da sucessora ainda não foi implementada/qualificada.

### Vínculo de autoria entre origem e sucessora

A inspeção dos gates encontrou um requisito adicional: Red, Green e freeze
conferem card/contrato de autoria. Copiar ou renomear recibos para a sucessora
falsificaria essa origem. `reassessment_origin` prepara a resolução explícita do
vínculo por proposta independente, mantendo recibos e autoria originais. Recusa
outro handoff, release, autor, autorrevisão e execução anterior à origem.

Esse resolvedor ainda não substitui verificações dos gates. Antes de conectá-lo,
o controlador deve conferir que a aprovação exata é input do card nativo atual;
a nova revisão deve gerar seus próprios recibos, sem herdar aprovação antiga.
A materialização do grafo e a prova completa permanecem pendentes.

### Integração offline dos gates de autoria

O card nativo fornece a aprovação explícita `reassessment_review`. A revisão de
testes, a revisão da implementação e o sandbox de leitura consultam a mesma
verificação de autoria. Sem essa autoridade, um recibo de outro card continua
recusado. Quando aplicável, a revisão nova e seu freeze registram a aprovação da
sucessão; o Red/Green original não é copiado nem reescrito. A leitura do freeze
reconfere essa linhagem. A suíte offline passou com 455 testes.

Isso ainda não materializa uma sucessora nem autoriza despacho. Permanecem
pendentes o handoff nativo da entrega preservada, a atualização segura das
dependências, a prova com interrupção/retomada e a obtenção, pela equipe, de uma
observação relevante que justifique reconsiderar o hold. Repetir a mesma suíte
pré-implementação não demonstra por si só a compatibilidade HTTP/console.
Runtime instalado e contador de chamadas permanecem inalterados.

### Transferência nativa da entrega preservada

`publish_review_handoff` usa a operação nativa `request_review` sobre a sucessora,
sem executar novamente o autor. O evento identifica explicitamente uma
transferência, com o recibo original e a aprovação da proposta. Exige proposta
concluída como dependência, origem ainda em triagem, ausência de efeitos
pendentes e autoria/snapshot exatos. Na implementação, conserva também os
controles originais e a separação entre autor dos testes e revisor.

A prova nativa programada verificou perda de confirmação depois da transferência,
repetição sem novo evento e preservação de uma revisão já reclamada. O vínculo
Red original → revisão sucessora foi aceito pelo gate real de autoria. A primeira
execução da prova falhou por fixture de incidente incompleta; a segunda passou
com incidente armazenado. Zero chamadas ao modelo ou Docker.

A ativação segue desabilitada: ainda falta publicar o grafo completo e assegurar
que uma interrupção entre desbloqueio e transferência seja reconciliada antes
do despacho. Essa prova não qualifica a atualização de dependências nem a
capacidade do agente de produzir a nova evidência que fundamenta a sucessão.

### Grafo de sucessão e janela de interrupção

A proposta de reavaliação agora fixa o grafo anterior. A materialização reutiliza
o mecanismo existente de continuação: preserva o prefixo concluído e a origem
em triagem, cria a sucessora e as dependências ainda não iniciadas, grava o grafo
antes de liberar trabalho e transfere a entrega original para revisão. Não
consome nem reinicia o contador de reparos de implementação ou fixture.

A prova nativa programada verifica interrupção depois da gravação do grafo,
dependências apontando para a nova revisão e implementação impedida de iniciar
antes dela. Outra interrupção ocorre após desbloquear e antes de transferir: o
controlador identifica a transferência incompleta e não despacha workers até
a reconciliação. O estado fica visível em `pending_review_transfers`. A repetição
com revisão ativa não altera seu claim. A prova anterior de correção de fixture
também passou novamente. Nenhuma dessas provas usou o modelo ou Docker.

Ainda não instalado: faltam a descoberta/ativação automática da proposta com
evidência nova, o caminho de mudanças solicitadas após reavaliação e a prova
completa até fechamento dos dependentes. O bloqueio de despacho é uma proteção
transitória, não uma solução para um incidente que permaneça sem responsável.

### Mudanças solicitadas e descoberta da continuação aprovada

O fluxo nativo programado agora percorre solicitação de mudanças, retorno ao
autor original, consulta do feedback persistente, novo handoff e outra revisão
independente. O gate rejeitou o Red antigo depois da nova submissão. Uma entrega
corrigida sob o contrato da sucessora usa sua própria autoria, sem reutilizar
a autoridade de transferência da entrega anterior. A implementação dependente
só pôde ser reclamada após o fechamento da nova revisão. Os recibos de qualidade
nessa prova são programados; não constituem novo Red/Green real do produto.

A reconciliação da release descobre propostas de reavaliação já concluídas a
partir do Kanban e do grafo anterior exato, materializa a continuação e reconstrói
a cadeia sem memória em processo. Propostas ambíguas ou circulares são recusadas.
Isso ainda não cria ou aprova automaticamente uma proposta: falta qualificar a
obtenção da evidência nova e sua passagem aos responsáveis Lead/CTO. A instalação
real continua em manutenção, sem novas chamadas pagas.

### Experimento técnico sobre cópia descartável

A admissão anterior exigia que toda observação nova viesse do mesmo snapshot
executado novamente. Isso impedia o CTO de testar a hipótese de viabilidade do
produto durante diagnóstico de fixture. O executor de mutações de produto já
existente agora pode ser usado também nesse diagnóstico: somente arquivos de
produto existentes, em cópia, com testes e configuração exatamente preservados.
A entrega do autor e o snapshot do handoff não são alterados.

O recibo registra snapshot de origem e snapshot experimental. A admissão da
reavaliação exige o job exato do experimento, relatório diferente do anterior e
reconfere a proteção de testes/configuração. A sucessora continua referenciando
a entrega original, nunca o experimento. Resultado diagnóstico não é Green de
entrega, freeze, aprovação, merge ou dispensa de controles.

Testes verificam recusa de enfraquecimento de teste, configuração de descoberta
alterada e origem estrangeira, além da preservação dos arquivos originais.
Ainda falta criar/ativar o SPIKE como atividade nativa delimitada após o hold e
ligar seu resultado à proposta Lead/CTO. Não houve instalação nem chamada paga.

### Acionamento nativo do CTO e passagem ao Lead

A reconciliação identifica o hold de revisão concluído pelo CTO e cria um único
SPIKE nativo por execução de origem. A criação exige card em triagem, contrato
e handoff exatos, decisão CTO concluída e ausência de efeitos pendentes. O SPIKE
tem o hold como dependência, prioridade técnica, zero retries automáticos e
600 segundos de execução. A repetição recupera o mesmo card, inclusive se ele
já encerrou; não inicia outra tentativa idêntica.

Somente uma conclusão vinculada ao run real do SPIKE pode alimentar a admissão
de evidência nova. Se admitida, ativa a proposta do Lead; a revisão independente
do CTO dessa proposta permanece necessária. Resultado ausente, observação
repetida ou falha deixa o incidente visível, sem liberar a entrega nem recriar
o experimento. A reconciliação da release inclui esse caminho.

A prova nativa programada passou pelo claim CTO, conclusão, deduplicação, ativação
da proposta, revisão, sucessora, mudanças solicitadas e liberação do dependente.
A admissão técnica continua programada nessa prova; os testes unitários cobrem
a proteção e procedência das evidências. A suíte passou com 458 testes. Falta
a prova combinada com job real e a inspeção final antes de instalar no S6.
Nenhuma chamada ao modelo ou container foi iniciada nesta etapa.

### Prova com jobs reais de validação

`scripts/qualify_reassessment_jobs.py` executou quatro jobs Docker reais com a
imagem local existente: baseline, Red, diagnóstico da entrega original e
experimento em cópia. O relatório diferente foi admitido pela função real de
sucessão, sem mocks nessa validação. As identidades de papel são programadas;
a prova nativa separada cobre o Kanban e esta cobre jobs/procedência/proteções.
Não equivalem ainda a um ciclo autônomo do modelo.

Os jobs usaram rede desabilitada, snapshot somente leitura e usuário sem
privilégios. Testes e snapshot original permaneceram idênticos. Nenhum recibo de
Green, freeze, aprovação de entrega ou homologação foi criado. O executor
retirou seus containers após preservar os resultados; nenhuma imagem nova foi
construída. Não houve chamada ao modelo.

A inspeção antes da instalação encontrou uma pendência adicional: o diagnóstico
de uma revisão sucessora precisa resolver a autoria transferida, em vez de
exigir sempre que o recibo original pertença ao card sucessor. Isso deve ser
corrigido e testado antes de instalar, para não recriar um impedimento no caminho
de falha. O S6 permanece em manutenção.

### Diagnóstico de falha da revisão sucessora

O diagnóstico resolve agora a autoria transferida pelo contrato exato do card e
registra essa autorização no incidente. A admissão de outra revisão pode conferir
a cadeia preservada. O resolvedor retorna o binding real do autor, sem fabricar
um novo número de execução. Handoffs corrigidos no próprio card continuam usando
a autoria nova, sem herdar a transferência antiga.

A prova nativa verificou a resolução do snapshot original durante a revisão
sucessora. Testes verificam recusa de ausência de autoridade e de contrato
alterado. A transferência posterior reutiliza a cadeia validada de recibos,
em vez de exigir indevidamente que o autor original pertença ao último card.
Isso não concede dispensa de revisão ou aprovação. O runtime permanece anterior
a estas mudanças, e o restante dos itens P2/P3 ainda precisa de fechamento antes
da retomada paga prevista na auditoria.

### P2 — Revisão de candidatos sem regra sintática universal

Novos recibos de Red de correção candidata usam `fixture_revision.contract=2`.
A autorização continua sendo a proposta independente, com arquivos existentes
explicitamente listados; o produto e a baseline entregue permanecem protegidos.
O comparador AST aditivo passa a ser relatório auxiliar para esse contrato.
Imports e helpers legítimos podem mudar dentro dos caminhos autorizados.

Permanecem bloqueados redução da quantidade de asserções por caso, remoção ou
renomeação de casos, skips, alteração da descoberta, mudanças fora dos caminhos
aprovados, modo do arquivo e alteração da baseline. A execução reconfere o
inventário completo e um Red apropriado; os controles obrigatórios anteriores
são preservados. Contagem/AST não provam que uma asserção continua forte: o
revisor precisa analisar a cobertura e os controles precisam demonstrá-la.

O contexto do revisor contém proposta autorizada, diff completo e relatório
estrutural. O diff agregado é limitado a 24.000 caracteres; uma correção maior
precisa ser dividida, nunca silenciosamente truncada. Recibos sem a versão nova
continuam usando o gate histórico: um teste confirmou que um candidato com
import novo não pode ser reinterpretado como aprovado sob o contrato antigo.

A suíte passou com 463 testes. A documentação/instruções do agente refletem o
novo escopo. Nenhuma entrega S6 recebeu aprovação, nenhum teste histórico foi
reescrito e o runtime ainda não foi atualizado. P3 e a migração controlada
continuam pendentes.

### P3 — Comparar resultados, não texto volátil

A admissão passou a comparar inventário e resultados por caso, incluindo
localização das falhas de asserção. Alterar somente mensagem de exceção, porta
efêmera ou hipótese não cria evidência nova. O identificador de deduplicação
usa esses resultados normalizados, preservando todos os relatórios originais.

Para propor reavaliação, o experimento precisa executar o mesmo inventário sem
erros, skips ou resultados especiais. Falhas de asserção continuam permitidas;
não se exige Green para rever Red. Um erro anterior às asserções permanece
evidência diagnóstica, mas não confirma viabilidade nem autoriza uma sucessão.
A relevância para a hipótese continua sendo responsabilidade do revisor técnico.

A matriz offline cobre hipótese sem observação, texto volátil, erro antes da
asserção, inventário parcial, evidência nova real, parecer antigo, interrupção,
deduplicação, autorrevisão e tentativa de enfraquecimento. A suíte de 463 testes
passou e os casos adicionais de admissão passaram. A prova de quatro jobs reais
foi repetida com o novo comparador. A avaliação semântica com o modelo e a
migração controlada permanecem pendentes; não se declara autonomia com essa
matriz. Nenhuma chamada paga foi executada nesta etapa.
# Complemento: feedback durante o SPIKE e migração única

O retorno de `diagnostic_validate` consulta o mesmo gate de admissibilidade da
reconciliação, sem conceder aprovação. Cinco jobs reais demonstraram recusa de
observação repetida e admissão de mudança verificável numa cópia, preservando os
testes. A identidade dos papéis nessa prova é programada, não julgamento autônomo.

O protocolo de SPIKE com feedback é versão 2. Uma instalação antiga pode criar
uma única sucessora para um SPIKE CTO concluído cuja observação passou pelas
verificações de escopo/job, mas manteve resultados normalizados idênticos. O
registro antigo não muda. Execução ativa ou com falha, resultado admissível e
outros erros não autorizam essa migração. A nova chave é idempotente e conserva
zero retries. Não se deve incrementar essa versão para repetir tentativas
sem mudança real de contrato. Prova nativa cobre deduplicação e preservação do
legado; a recuperação real do S6 continua requisito separado.

