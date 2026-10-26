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

Após os mecanismos anteriores passarem offline:

1. Preparar atualização explícita do código executado em manutenção drenada,
   mantendo exportação, recibos, deploy e teste da primeira versão. Não sobrescrever
   a revisão que qualificou S4 nem atualizar workers em voo.
2. Produto propõe um pequeno incremento com dois pacotes verticalmente úteis e
   dependentes. Reset do formulário e desfazer o último reset são uma opção de
   demonstração, ainda sem aprovação de negócio; Produto pode propor alternativa.
3. Apresentar o novo brief ao CEO. A autorização condicional do documento da
   primeira versão não aprova outro conteúdo. Não pedir novamente decisões já
   registradas e não encaminhar escolhas técnicas ao CEO.
4. Fixar código/configuração antes da execução. Depois do aceite, a equipe conduz
   o novo grafo; o operador observa. Preservar todos os nove testes anteriores e
   seus contratos QA, acrescentando somente as provas do incremento.
5. Registrar uso de memória por outro perfil, dependências efetivamente liberadas,
   revisão independente e regressões completas em cada integração.
6. Comprovar uma recuperação pela equipe com fonte e próxima ação duráveis. Uma
   injeção de falha deve ser planejada e isolada, sem interromper requisição paga,
   mexer no daemon Docker ou afetar Toso. Falhas específicas podem ter fixtures
   separadas; não repetir a versão paga inteira para cada falha de transporte.
7. Exigir nova `HOMOLOGADA`, CI/deploy/QA no mesmo commit, rollback e evidências.

Se precisar de reparo externo, manter o valor da entrega como assistida sem
reclassificar a qualificação. Não apagar a primeira versão nem resetar o board.

## 4. Recursos, custo e distribuição

- Manter Haiku, 40 iterações, dois workers e nenhum fallback. No fim de S4 o
  contador estava em 6.811/7.000; são 189 chamadas restantes, não um teto em USD.
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
