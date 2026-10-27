# S5 — Continuidade de implantação entre releases

## Defeito e reparo

O primeiro pacote de cada release retornava `None` como artefato anterior.
A integração interpretava isso como primeira instalação e construía um bootstrap,
mesmo quando havia uma homologação anterior do próprio projeto em execução.
A guarda de rollout recusava substituir o artefato existente: comportamento
correto de proteção, com seleção incorreta do rollback.

`Releases.accepted_rollback` reutiliza a última aceitação nativa do mesmo projeto.
Confere recibo de homologação, QA independente, papel do artefato, imagem, commit,
snapshot e correspondência com o seed da nova release. A memória histórica ajuda
a localizar esse recibo; não concede aprovação ao trabalho novo.

- Sem homologação anterior: mantém o bootstrap validado.
- Primeiro pacote de uma release posterior: usa o artefato homologado exato.
- Pacotes seguintes: mantêm o artefato da QA do pacote imediatamente anterior.
- Plano corretivo: mantém sua autoridade específica existente.
- Deployment divergente ou ambíguo: permanece bloqueado e preservado.

O diagnóstico de integração recebe observação fixa e somente leitura do serviço
validado: grupo, container, imagem, artefato, URL, saúde e rede, além da referência
à homologação anterior. Não recebe ambiente Docker, credenciais ou comandos
administrativos. Falha de observação não autoriza substituição.

## Validação reproduzível

Além dos testes unitários, o qualificador existente ganhou `--continuity`.
Ele entrega dois pacotes em uma primeira release e um pacote numa segunda,
verificando que o rollback da segunda reutiliza exatamente o artefato da primeira.
Executa Git, ciclo nativo Hermes, Docker e QA de navegador reais. As decisões dos
agentes e o transporte GitHub são fixtures programadas; não comprova autonomia
nem GitHub real. Não há chamadas pagas.

```sh
python scripts/qualify_hermes_release.py \
  --root /caminho/privado/novo-ensaio \
  --upstream /caminho/hermes-fixado \
  --image sha256:DIGEST_DO_VALIDADOR \
  --browser-image sha256:DIGEST_DO_NAVEGADOR \
  --namespace delivery-kit-hermes-continuity \
  --continuity
```

Em hosts com pools automáticos esgotados, o harness aceita `--network-pool` com
um bloco IPv4 privado `/27`, dividido em duas redes `/28`. Antes da criação,
recusa sobreposição com redes Docker existentes ou nomes já ocupados. Essa opção
pertence ao ensaio, não modifica a política da instalação produtiva. O operador
deve escolher um bloco compatível também com as rotas de seu ambiente.

O recibo `continuity-receipt.json`, privado, registra as duas aceitações, o
artefato reutilizado, os três passos candidate/rollback/restore e a preservação
dos testes. A limpeza só retira recursos exatos do ensaio depois da evidência,
sem volumes ou outros projetos.

## Resultado da qualificação de 27/10

A execução completa passou com duas releases, três pacotes, 18 atividades SDK
e 27 respostas HTTP programadas. A segunda release reutilizou exatamente o
artefato anterior nos três passos candidate/rollback/restore, preservou os testes
e reexecutou QA. A retirada exata do deployment e das redes descartáveis ocorreu
depois da evidência. O núcleo passou em 344 testes sob Python 3.14.10.

As tentativas anteriores foram preservadas: uma encontrou esgotamento de pools
automáticos Docker; outra perdeu o executável Homebrew do ambiente virtual.
Nenhuma foi convertida em sucesso. O ensaio completo não usou chamadas pagas.

## Observação e escalonamento qualificados

A observação liga explicitamente o artefato atual ao recibo de QA e à aceitação
anterior. Comparar apenas projeto, nome ou commit é insuficiente: o campo
`current_is_previous_homologation` exige o mesmo artefato e imagem. Um erro
histórico contendo a palavra “unrelated” não classifica o deployment atual.
Essa informação permite ao diagnóstico avaliar a relação real sem acesso ao
Docker administrativo ou autorização para dispensar QA.

Um `hold` do Tech Lead mantém sua decisão e o bloqueio, mas cria automaticamente
um diagnóstico CTO vinculado ao predecessor. O CTO pode manter um impedimento
visível com próxima ação concreta; não há recursão nem decisão técnica enviada
ao CEO. O qualificador nativo de sucessores comprovou hold preservado, fonte
nunca desbloqueada e ausência de duplicação após reinício, sem modelo ou Docker.

## Memória diagnóstica sem instruções herdadas

O contexto enviado ao CTO continha a relação correta entre artefatos, mas
reenviava o veredito livre do diagnóstico anterior sem marcar sua natureza
histórica. O modelo repetiu a orientação antiga. Isso demonstra a falha da
decisão observada; a ancoragem pelo histórico é uma hipótese a revalidar.

O novo repasse inclui apenas referência ao diagnóstico, autoria/run, ação e
resultado do experimento vinculado. Não injeta o antigo veredito como nova
instrução. O texto original permanece no recibo imutável para auditoria. Não
transfere autoridade ou aprovações. O contexto também deixa de repetir a
arquitetura inteira da homologação anterior em cada diagnóstico de deployment.

O SPIKE de integração registra novamente os fatos atuais do serviço, ligados
à sua própria execução. A prioridade é o contrato instalado, as observações
atuais e o experimento novo. Uma decisão antiga não exige outro hold quando
as condições verificadas mudaram; divergências reais continuam bloqueadas.

A regressão do contrato foi reproduzida em dois testes e a suíte passou em
344 testes. O fluxo isolado com SDK/Kanban/Docker passou em nove runs e 29
respostas programadas, sem chamadas pagas. A mensagem efetivamente entregue
ao SDK foi conferida: histórico identificado, evidência preservada e ausência
do veredito livre antigo. Isso não substitui a próxima decisão do modelo real.

## Limites

A nova release deve começar exatamente no commit/snapshot da homologação anterior.
Alterações externas na base permanecem sujeitas a diagnóstico; este reparo não
qualifica migração arbitrária de branches nem implantação genérica de uma base
com regressão conhecida. CI de regressão e continuidade de deployment são provas
distintas. A tentativa S5 em andamento permanece assistida, mesmo se for entregue.

Na retomada de um Mac, uma mudança de hostname pode tornar claims históricos
aparentemente estrangeiros. A observação permite reconhecer a morte de um run
já encerrado pelo PID e fingerprint registrados. Não autoriza matar processos,
reclamar claims ativos estrangeiros ou prosseguir diante de identidade incerta.
