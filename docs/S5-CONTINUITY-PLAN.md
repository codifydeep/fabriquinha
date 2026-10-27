# S5 — Continuidade depois do primeiro S4

Plano de execução em 26/10/2026, dentro dos refinamentos já aprovados. O
[S4](HERMES-S4-QUALIFICATION.md) passou; não reabrir outra instalação para repetir
a mesma saudação. O objetivo agora é evoluir a aplicação já homologada, manter
seus testes e provar memória/recuperação, antes da distribuição e do Truco.

## 1. Preparar os contratos antes de gastar mais chamadas

**Implementado e qualificado localmente:** ver [contratos e prova](S5-CONTRACT-QUALIFICATION.md).
O caminho nativo SDK/Git/Docker passou com decisões programadas e zero chamadas
pagas. Ainda não é uma nova release autônoma.

Implementar a distinção aprovada na seção A2 da
[auditoria de 26/10](EXECUTION-REVIEW-2026-10-26.md):

- Funcionalidade nova continua exigindo base verde e teste comportamental novo
  vermelho. Não mudar esse caminho para acomodar uma regressão.
- Regressão conhecida exige teste existente falhando no SHA defeituoso. O revisor
  confirma a expectativa e as falhas exatas; o autor corrige o produto, mantendo
  os testes protegidos. Não duplicar artificialmente um teste que já demonstra
  o defeito.
- A CI aceita somente as falhas de base previamente revisadas, no SHA e no
  inventário exatos; erros adicionais, skips, descoberta parcial ou cabeça
  vermelha continuam impedindo integração.
- O modo vem do estado/recibo validado pelo controlador. O executor não escolhe
  uma exceção por declarar que seu trabalho é uma regressão.
- Recibos antigos não são convertidos. Red normal e a correção restrita de texto
  QA permanecem caminhos distintos. Nenhum reset de retries, triagem ou histórico.

Reusar Quality, Store, revisão, CI e Kanban existentes. Preferir um tipo de
evidência explícito e validação pequena a outro serviço ou motor de workflow.
Qualificar em Git/Docker e SDK locais: defeito preexistente, revisão, reparo,
controles, CI verde; recusar SHA/falha/inventário divergentes e revisão obsoleta.
Decisões programadas devem permanecer identificadas como fixtures.

## 2. Memória de projeto mínima e verificável

**Projeção implementada e testada:** origem e revisão foram lidas dos recibos do
S4 real. Falta comprovar uso por outro perfil na segunda versão, conforme abaixo.

O código atual guarda decisões duráveis, mas o contexto de planejamento contém
somente o brief/plano atuais. Não concluir que memória entre versões existe
apenas porque sessões e arquivos antigos sobreviveram.

Preparar uma projeção somente leitura da última release homologada deste mesmo
projeto: commit, referências de evidência e decisões técnicas relevantes do
plano aprovado. Servir somente o necessário aos perfis consumidores, com tamanho
limitado; não copiar conversas ou o histórico inteiro para cada prompt.

Rotular decisões anteriores como contexto histórico, sem aprovar trabalho novo,
conceder ferramentas ou dispensar revisões. Preservar identidade de projeto,
origem e revisão. Testar ausência de história, outra instalação, dados adulterados
e rejeição de aprovações antigas como autorização da versão nova.

A prova real deverá mostrar outro perfil citando uma decisão anterior e seu
efeito no plano/código, com fonte verificável. Informação apenas disponível no
prompt, sem evidência de uso, não basta. Não instalar um banco vetorial agora.

## 3. Segunda versão real, na mesma aplicação

**Iniciado e drenado por impasse de revisão:** controlador atualizado em manutenção drenada, com backup nativo
verificado e exportação publicada `2bd47470`. Produto apresentou Reset e Undo de
um nível; CEO aprovou o novo brief. Não reutilizar esse checkpoint como prova de
homologação ou de recuperação. Aplicar o [escalonamento obrigatório](S5-REVIEW-IMPASSE.md)
e retomar o mesmo ciclo, sem converter a tentativa em qualificação autônoma.
A equipe ainda deve concluir os passos abaixo.

O escalonamento foi instalado e exercitado pelo modelo real. A clarificação de
proveniência e a chave sucessora vinculada ao predecessor também foram publicadas
e instaladas; outro diagnóstico CTO está atendendo o encaminhamento do Lead.
Preservar os três pontos de assistência, o `hold` anterior e os mesmos cards.

**Próxima correção concreta:** após os reparos de feedback, os testes de Reset
foram congelados, o frontend implementou e o PR 60 foi integrado. A integração
parou na seleção do rollback da segunda release: o primeiro pacote não reconhece
o artefato homologado anteriormente na mesma instalação. Qualificar primeiro
essa continuidade com Git/Docker e identidade exata de artefatos; só então
retomar o mesmo card por diagnóstico. Não remover a implantação preservada,
substituir a guarda por comparação de nomes ou criar outra release para contornar.

O brief Reset/Undo já foi aprovado, o grafo de dois pacotes foi criado e Reset
foi implementado e revisado. **Não repetir entrevista, aceite ou criação de cards.**
Os próximos passos são:

1. Qualificar a [continuidade de implantação](S5-DEPLOYMENT-CONTINUITY.md) em
   ambiente descartável, preservando também tentativas que falharem por ambiente.
2. Atualizar o código executado somente em manutenção drenada, com backup
   restaurável e exportação imutável. Preservar o S4 e suas evidências originais.
3. Encaminhar o incidente existente para novo diagnóstico técnico com as novas
   observações. A equipe deve executar um experimento e decidir a retomada;
   manutenção não desbloqueia diretamente o card nem aprova a entrega.
4. Concluir implantação e QA independente de Reset. Somente então liberar os
   cards dependentes de Undo, com Red, freeze, Green, controles negativos,
   revisão independente, PR e CI próprios.
5. Conferir a nova `HOMOLOGADA`, todos os critérios aprovados, testes anteriores
   e QA reexecutados, CI/deploy/QA no mesmo commit, rollback e recibos duráveis.
   Registrar memória entre perfis, recuperação, consumo e intervenções externas.

Se precisar de reparo externo, manter o valor da entrega como assistida sem
reclassificar a qualificação. Não apagar a primeira versão nem resetar o board.

## 4. Recursos, custo e distribuição

- Manter Haiku, 40 iterações, dois workers e nenhum fallback. O contador no
  bloqueio de deployment estava em 6.908/7.000; são 92 chamadas restantes,
  não um teto em USD. Consultar o relay antes de novas atividades.
- Usar provas offline para mecanismos e registrar custos reais do novo ciclo.
  Pedir aumento somente se a reserva necessária não couber no teto autorizado.
- Repetir previews de limpeza nos limites do ciclo; somente recursos próprios,
  ociosos e obsoletos. Preservar deploy, rollback, volumes e Toso.
- Após S5, S6 precisa provar instalação limpa em outro repositório, credenciais,
  upgrade/rollback, canais/status, entrega ao CEO e retirada do legado. A fila da
  outbox de S4 não é prova de entrega Telegram.
- Integrar ao lifecycle a aposentadoria de branches de feature somente após PR
  merged, conteúdo preservado, ausência de leases e revalidação do SHA exato.
  Nunca remover a branch de release atual para liberar capacidade.

Isso mantém a sequência aprovada sem criar novas camadas de orquestração. O
objetivo global permanece aberto até continuidade, distribuição e retomada do
produto nas fronteiras previstas pelo roadmap.
