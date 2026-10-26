# Fechar a lacuna de QA e retrabalho da mesma release

Estado: A e B implementados em fonte e qualificados no escopo abaixo; C e sua
qualificação continuam pendentes. Não concede aprovação de entrega ou exceção aos testes. Continua
o objetivo de autonomia; não é outro orquestrador nem uma migração de modelo.

**Revisão posterior, aceita em 26/10:** a [auditoria de 26/10](EXECUTION-REVIEW-2026-10-26.md)
recomenda substituir C por um pacote corretivo limitado, sem regerar todo o plano,
e classificar a divergência entre o brief e o QA antes de corrigir o produto.
A/B permanecem implementados; C abaixo preserva a proposta anterior para comparação.
A auditoria preservou a pausa; o proprietário autorizou depois a execução do
[reparo mínimo](ADR-0004-SCOPED-REPAIR.md). C abaixo permanece como histórico, não
como instrução para implementar gerações integrais do plano.

## Evidência que motivou a mudança

O mesmo brief aprovado chegou a Red/freeze, Green de oito testes, seis alvos
negativos, revisão independente, PR 56, CI no SHA exato, merge e deploy com
rollback/restauração. O commit integrado é
`b9f5d55fd4c5bef8061d04cf718a8b83336a3679` em
`release/fabriquinha-s4-ci-2`. O QA implantado recusou a entrega: o contrato
congelado exige texto exatamente `Ana` em `#greeting`, mas recebeu
`Hello, Ana! Welcome.`. Dois jobs de navegador registraram o mesmo erro.

O CTO recebeu somente a mensagem genérica do gate, rodou a suíte local verde
e retomou o mesmo QA imutável. A repetição levou à triagem nativa e foi mantida
como bloqueio. Não há recibo de homologação. A última cota observada é
6.627/7.000; modelo, raciocínio e saída 16.384 continuam iguais.

Há três problemas distintos: semântica pouco explícita do protocolo de QA,
duas definições de comportamento que não são executadas juntas antes do merge,
e ausência de um caminho real para replanejar após uma falha funcional de QA.

## Invariantes

- Não transformar `to_have_text` em substring para fazer o teste passar.
- Não editar os testes/QA congelados, dispensar CI ou aprovar o commit anterior.
- Não zerar breaker ou reabrir repetidamente a mesma revisão imutável.
- Não apagar a implantação, os workspaces, snapshots, PRs ou relatórios antigos.
- Decisões técnicas pertencem a Lead/CTO. O brief já aprovado não será repetido.
- Uma correção de código que preserve o brief e todos os testes não exige
  nova decisão de negócio. Uma exceção ao contrato de testes exige autorização
  específica; não será introduzida implicitamente pelo retrabalho.
- Só `HOMOLOGADA` com QA no commit efetivamente implantado conclui a release.

## A — Fatos completos e semântica única

1. Explicitar no schema/documentação que `text` compara o texto completo do
   locator com normalização de espaços; não significa `contains`.
2. Recusa de QA deve identificar o job, commit, checks concluídos e erro real.
3. Guardar referência ao `browser_job` já existente no `worker_failure` e no
   incidente. Validar projeto, execução, imagem, snapshot, SHA e sandbox antes
   de expor os fatos. Não criar outra cópia da conversa ou outro banco.
4. Distinguir falha comportamental de infraestrutura; ambas continuam negativas.
   Um SPIKE de unittest verde não substitui o QA que falhou no navegador.

## B — Executar o contrato congelado antes de aprovar Green

Usar o mesmo interpretador de `browser.py` nos dois ambientes. Não manter dois
interpretadores com comparadores diferentes.

- Em Green, revalidação da entrega e CI integrada, executar a suíte completa
  e depois os contratos QA congelados contra uma instância HTTP local efêmera
  da mesma árvore. Nada de rede externa, credenciais, socket ou publicação de
  porta no host. Red/controles conservam seus alvos e inventário atuais.
- A prévia de QA fica como campo separado do relatório confiável: não inventar
  novos casos unittest nem converter QA em prova histórica de Red.
- Vincular resultado ao snapshot e aos hashes dos scripts confiáveis. Reusar
  scripts montados somente leitura, como já acontece no QA implantado, evitando
  reconstruir imagens a cada ajuste de protocolo. Inspecionar mounts, entrypoint,
  ambiente e hashes exatos; não aceitar código escolhido pelo agente.
- Green/revisão/CI recusam a ausência, falha ou divergência dessa prévia quando
  exigida. Recibos antigos sem a prova não passam a satisfazer a nova exigência.
- O pós-deploy continua obrigatório, com SHA real, imagem, URL, health e rollback.

## C — Retrabalho versionado, dentro da mesma release

Não fazer outro reset/brief como resposta padrão a um QA funcional recusado.

1. Uma falha real de `browser_job`, vinculada ao rollout atual e sem efeito
   Docker incerto, gera uma solicitação durável de resolução técnica ao Lead.
   Deduplicar pela causa observável, não pelo número de retries do worker.
2. O Lead produz uma revisão do plano no Kanban, com o mesmo brief e todos os
   seus critérios, usando o relatório real e o código atual como contexto.
   O CTO faz a revisão independente. Não prescrever ao modelo uma solução de
   implementação escrita pelo operador.
3. Durante o replanejamento, suspender novos despachos da geração antiga e
   aguardar processos/leases/efeitos em andamento. Não matar trabalho saudável.
4. Planos e grafos anteriores permanecem imutáveis. Selecionar o plano aprovado
   atual pela cadeia de revisões no Kanban; guardar cada seed/grafo por revisão.
   Não adicionar um segundo ciclo de vida fora do Kanban.
5. A nova geração recebe workspaces novos, baseados no SHA atual da branch.
   IDs, dependências e admissões pertencem à geração correta. Revalidar a base
   antes de ativar; não continuar sobre branch que mudou silenciosamente.
6. Preservar cards concluídos e a triagem anterior como histórico. Estacionar
   cards pendentes substituídos com comentário e vínculo à nova geração; não
   marcá-los como entregues nem usar `archive_task` sem provar que seu cleanup
   preserva os workspaces. Não alterar os contadores antigos.
7. Recuperação, alertas e status distinguem geração atual de trabalho substituído.
   Um card histórico não pode ser despachado, retomado ou causar alerta repetido
   como impedimento corrente.
8. A equipe reproduz a falha em um novo teste de regressão, obtém Red/revisão/
   freeze e corrige o produto preservando os arquivos de teste preexistentes.
   O PR independente usa a base integrada atual e passa novamente por CI,
   integração, deploy, rollback e QA. Não reutilizar aprovação de outro SHA.
9. A aceitação considera o grafo atual e cobertura integral do brief; vincula o
   retrabalho às evidências negativas anteriores sem declará-las aprovadas.
10. Repetições sem mudança de evidência exigem diagnóstico; não gerar infinitas
    revisões equivalentes. Falha de infraestrutura não vira tarefa de produto
    por mera suposição. O responsável e a próxima ação ficam visíveis.

## Qualificação já realizada de A/B

O núcleo passou em 285 testes. A prova `scripts/qualify_browser_preview.py`
executa sete jobs Docker/Chromium, todos com snapshot somente leitura, rede
`none`, usuário sem privilégios e sem credenciais/socket. Uma unidade que aceita
saudação contendo o nome passa sozinha; o QA exige exatamente o nome no locator.
Green, revisão e CI recusam a contradição. A correção somente de código passa
nos mesmos testes e no mesmo QA, sem alterar seus bytes. Os jobs são agrupados
e aposentados pelo executor, com recibos privados preservados.

Os hashes do reporter e do interpretador pertencem à identidade dos jobs de
prévia. Mounts, entrypoint e ambiente são conferidos. Recibos históricos sem a
prévia exigida não satisfazem o novo gate; aprovação de QA implantado permanece
separada. A prova é programada, sem SDK/modelo/GitHub ou lifecycle de release:
não demonstra recuperação autônoma nem aprova a tentativa real preservada.

```bash
PYTHONPATH=src python scripts/qualify_browser_preview.py \
  --root /caminho/privado/novo-browser-preview \
  --image sha256:DIGEST_DO_VALIDADOR_COM_CHROMIUM
```

O primeiro fixture tinha um erro de quoting em seu próprio HTML e não qualificou
o mecanismo. Foi preservado como falha de preparação; nenhuma evidência dessa
tentativa foi reaproveitada como aprovação.

## D — Qualificação antes de novas chamadas ao modelo

- Texto `Hello, Ana!` deve falhar quando o contrato exigir exatamente `Ana`.
- Uma suíte unittest verde com esse conflito não pode obter Green, revisão ou CI
  aprovadas. Corrigir código sem mudar o QA pode satisfazer ambos; não enfraquecer
  comparação ou modificar o artefato antigo para demonstrar isso.
- O mesmo interpretador deve aprovar/recusar a prévia e o QA implantado.
- Relatório negativo completo chega ao Lead/CTO; snapshot/SHA estrangeiros,
  relatório incompleto e falso sucesso são rejeitados.
- QA falho cria um replanejamento só, inclusive após reinício. O CTO revisa.
- Aguardar quiescência antes de substituir trabalho; preservar bytes e histórico.
- Cards antigos não retornam ao dispatcher nem disparam alertas de atividade atual.
- O novo Red reproduz uma falha pós-deploy e preserva testes antigos; o PR corretivo
  usa a base atual. A release só termina após QA positivo da correção implantada.
- Exercitar pelo menos uma falha que só aparece no ambiente implantado, mesmo
  com a prévia local, para demonstrar o caminho de retrabalho real.

Usar SDK/Kanban/Docker reais e respostas locais programadas, distinguindo prova
de mecanismo de julgamento do modelo. Depois, revalidar com Haiku na cota
autorizada. Preferir continuar o caso real preservado quando seguro; registrar
a intervenção do operador como tentativa assistida. Uma futura fronteira sem
intervenção externa ainda será necessária para qualificar S4 autônomo.

## O que não foi concluído

A primeira entrega autônoma completa ainda não foi comprovada. Segunda versão,
memória entre versões, exceções versionadas aos testes, transporte Telegram,
instalador portável/cutover e retomada do Truco permanecem necessários. Não trocar
de modelo, criar outro orquestrador ou redesenhar todo o sistema para ocultar
essa lacuna concreta.
