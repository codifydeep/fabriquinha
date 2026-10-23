# Status do projeto — 23 de outubro de 2026

**Experimental. Autonomia completa ainda não qualificada.** Este é um resumo
datado da instalação de referência, não uma consulta de estado vivo nem uma
garantia de funcionamento em outra instalação. Evidências operacionais,
conversas, credenciais, snapshots e bancos permanecem privados.

## Objetivo e critério de conclusão

Receber um brief, refiná-lo com Produto, obter aprovação de negócio e entregar
software em homologação por uma equipe de agentes: planejamento, cards
dependentes, TDD, revisão independente, PR/CI e implantação/QA/rollback no mesmo
commit. O operador não deve precisar dirigir handoffs ou reparar cada etapa.

O único sucesso terminal da release é `HOMOLOGADA`, com evidências verificáveis.
Um worker ativo, teste offline verde ou bloqueio corretamente detectado não
substitui esse resultado. O Truco permanece fora da execução de produto até a
qualificação da equipe. Temporal não está implementado como motor do runtime.

## Estimativa de prontidão

| Área | Estimativa |
|---|---:|
| Infraestrutura, isolamento e controle de acesso | 90% |
| TDD, proteção de testes e revisão imutável | 80% |
| Coordenação e handoffs autônomos | 65% |
| Recuperação de falhas sem intervenção do operador | 60% |
| Instalação reutilizável e qualificação completa | 55% |
| **Consolidado** | **70%** |

São estimativas de engenharia, não cobertura de testes, taxa de sucesso, SLA ou
comprovação de autonomia. Não resultam de um índice automatizado. Não comparar
estimativas históricas como uma série de medições com metodologia constante.
Os critérios objetivos continuam em [ROADMAP.md](ROADMAP.md).

## O que foi comprovado e o que não foi

- Há fluxos históricos descartáveis com revisão, PR/CI e QA no mesmo commit,
  mas com reparos do operador. Eles não qualificam um novo ciclo sem intervenção
  nem transferem aprovação para o contrato de qualidade atual.
- O controlador de qualidade v2 está instalado para qualificação controlada,
  com isolamento de fases, snapshot imutável e autorização por execução.
- O autor real produziu Red: 381 testes Python executados, falhas de asserção
  restritas ao teste novo, e 36 testes Node aprovados, sem erros ou skips.
- O coordenador devolveu uma solicitação de mudanças ao mesmo autor, que
  corrigiu os testes. Isso comprova esse handoff, não a cadeia completa.
- O proxy com limite de requisição de 2 MiB foi qualificado e instalado sem
  zerar o contador de chamadas. O ensaio seguinte ultrapassou o antigo limite
  de 512 KiB sem aquela rejeição de tamanho.
- A revisão nativa mais recente falhou após consumir 40 iterações. A inspeção
  integral foi comprovada para 57 dos 71 arquivos; não houve aprovação nem
  congelamento dos testes, Green ou homologação nessa linhagem.
- A suíte offline da candidata com captura, enforcement e paradas executou
  **4.362 testes: 4.354 aprovados e oito skips preexistentes**, sem falhas.
  Os 81 testes focados também passaram. Isso qualifica o comportamento offline,
  não instalação, execução física do novo módulo ou autonomia nativa.

## Bloqueio atual

O revisor repetiu páginas já servidas e tentou ler além do fim de um arquivo,
sem completar o escopo obrigatório dentro do orçamento. O cache é indexado por
arquivo, offset e limite; não foi demonstrado defeito nessa chave. A lacuna é
permitir chamadas sem progresso e não orientar suficientemente as páginas
pendentes. O erro genérico nativo não deve ser confundido com a antiga rejeição
por tamanho ou com uma falha funcional demonstrada do produto.

O feedback antes do encerramento está instalado, mas ainda não resolve essa
classe de esgotamento. O núcleo do diário limitado e do planejador de páginas
pendentes foi implementado **em uma candidata, ainda não instalada**. A captura
ocorre na entrada do loop e após os resultados das ferramentas, antes da
compactação seguinte. O handler admite uma única entrada por página planejada;
a checagem anterior do despacho não consome essa entrada. Chamadas diretas e
concorrentes também são restringidas. O feedback preserva páginas capturadas,
reconhece progresso parcial e interrompe bytes divergentes ou ações sem progresso.
Uma fixture de 71 arquivos e 81 páginas concluiu a fila simulada dentro de 40
iterações, sem páginas repetidas ou além do fim; não é execução de modelo real.

O canário físico da candidata passou com Hermes/ACP e respostas locais fixas:
continuação normal, despacho seguido de handler, negação de leitura duplicada,
saída `read_progress_stalled` e saída `iteration_budget_exhausted`. Foram sete
respostas locais, sem modelo externo. O caso de orçamento usa um loop de uma
iteração como controle de fronteira; a fábrica ACP continua vinculada a 40.
Isso não comprova uma revisão nativa completa com 40 iterações.

Ainda faltam paginação extensa e compactação forçada no Hermes real,
instalação e recuperação específica seguidas de qualificação nativa. A memória
é local à execução, não recuperação
entre reinícios ou memória compartilhada entre perfis. Não há nova aprovação
implícita nem autorização para repetir a mesma tentativa indefinidamente.

Na consulta de referência, o controlador está sob manutenção selada, sem
execuções ativas, e o proxy do modelo está parado. Essa condição pode mudar:
consulte o runtime antes de qualquer intervenção. Esta documentação não inicia
serviços, libera manutenção ou consome chamadas ao provedor.

## Próximos marcos, em ordem

1. Implementar paginação orientada por evidência: preservar leituras reais entre
   compactações, selecionar apenas páginas pendentes e reconhecer progresso
   parcial. Coleta, enforcement e saída estruturada já estão na candidata;
   completar a qualificação de escala/compactação. Não reduzir o escopo de
   aprovação ou ampliar as 40 iterações.
2. Qualificar offline e em Docker/ACP os casos de múltiplos arquivos, cache,
   fim de arquivo, contexto compactado, ausência de progresso e fim do orçamento.
3. Instalar sob manutenção e preparar recuperação vinculada à condição realmente
   corrigida. Preservar a falha anterior; não reutilizar prova de capacidade do
   proxy para uma falha diferente. Só então iniciar outro ensaio nativo.
4. Comprovar revisão e congelamento, Green, controles negativos, revisão da
   entrega, PR/CI e implantação/QA/rollback no mesmo commit sob o contrato v2.
5. Demonstrar diagnóstico e recuperação por Tech Lead/CTO, novo brief com cards
   dependentes e memória entre perfis, sem condução do operador.
6. Qualificar instalação limpa e reutilização por terceiros antes de apresentar
   a plataforma como pronta. A fatia inicial do Truco não encerrará sua v0.1.

## Navegação

- [Arquitetura e fronteiras de autoridade](ARCHITECTURE.md)
- [Validação atual e evidências históricas](VALIDATION.md)
- [Critérios objetivos e trabalho restante](ROADMAP.md)
- [Instalação segura](SETUP.md)
- [Recuperação de QA e revisão](QA-PROTOCOL-RECOVERY.md)
- [Limites dos recibos de patch](PATCH-RECEIPTS.md)
