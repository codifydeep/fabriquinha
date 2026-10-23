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
- O diário de leituras, a captura no loop, o enforcement e as paradas
  estruturadas foram qualificados e instalados. A troca preservou dados e
  configurações, com backup compactado e restauração verificados. O serviço
  host foi migrado para o novo pin, sem resetar sua fila ou seu histórico.
- Após uma recuperação restrita, o coordenador iniciou outra revisão nativa.
  Ela consumiu sete chamadas e terminou com diagnóstico `read_progress_stalled`:
  16 dos 71 arquivos tiveram leitura integral comprovada. O controlador manteve
  `technical_blocked`, sem aceitar o diagnóstico como parecer ou aprovação.
- A última suíte offline registrada com captura, enforcement e paradas executou
  **4.372 testes: 4.364 aprovados e oito skips preexistentes**, sem falhas.
  Os 91 testes focados também passaram. Esses números não representam uma nova
  execução por ocasião desta atualização documental nem autonomia nativa.

Não houve congelamento dos testes, Green ou homologação nessa linhagem v2.

## Bloqueio atual

A fila de páginas pendentes só passa a orientar o pedido ao modelo **depois de
uma tentativa prematura de resposta final**. No código instalado,
`quality_review_stop.apply_request()` retorna o pedido sem essa orientação
quando ainda não existe `_quality_review_completion`. O modelo pode, portanto,
usar ferramentas desde o início sem receber a fila, o schema restrito e o gate
por página. O monitor de progresso continua ativo e interrompe a execução,
mas não supre essa lacuna de orientação inicial.

O ensaio mais recente seguiu esse caminho e parou com 33 iterações ainda
disponíveis. O estado nativo `completed` significa que a execução terminou,
não que a revisão foi aprovada. O recibo do controlador registra
`native_terminal_verdict`, formato inválido para parecer e `automatic_retry=false`.
O diagnóstico estruturado não é uma falha funcional comprovada do produto.

A tentativa anterior, com 57/71 arquivos completos e 40 iterações consumidas,
permanece preservada como falha distinta. A rejeição histórica por corpo acima
de 512 KiB também não é a causa comprovada do bloqueio atual. Não se deve
reutilizar a prova de capacidade do proxy para autorizar uma repetição idêntica.

## Alcance da qualificação já feita

O canário Hermes/ACP passou com respostas locais fixas: continuação após uma
resposta prematura, despacho seguido de handler, duplicata negada e paradas por
ausência de progresso e fim do orçamento. A extensão inspecionou 71 arquivos,
563.066 bytes e 219 páginas em 23 chamadas principais e duas sumarizações locais.
Duas compactações reais removeram 197 pares da conversa sem perder a cobertura
no diário. O conjunto usou 32 respostas locais, sem chamadas ao provedor.

Essa prova **não cobriu a orientação desde a primeira chamada de um modelo que
só usa ferramentas**. Também não comprova aprovação nativa, memória entre
reinícios ou memória compartilhada entre perfis. O controle de fronteira do
orçamento usa uma iteração sintética; a fábrica ACP mantém 40.

## Instalação de referência consultada

| Item | Estado observado em 23 de outubro |
|---|---|
| Controlador de qualidade | `delivery-kit-quality-v2-controller:20261023.30`, instalado e ativo |
| Worker de autoria/revisão | Seletor `delivery-kit-quality-author-worker:20261023.6` |
| Manutenção | `sealed`, `drained=true` |
| Última revisão | Nativa `completed`; atestação e equipe `technical_blocked` |
| Proxy | Ligado, provedor não pausado; limite de corpo de 2 MiB |
| Contador do proxy | 6.254/10.000 chamadas, 3.746 restantes; não é limite monetário |

Manutenção selada não significa proxy desligado. Esta é uma fotografia, não
monitoramento vivo: confirme serviços e leases antes de agir. Esta atualização
documental não inicia testes, libera manutenção ou altera a infraestrutura.

## Próximos marcos, em ordem

1. Aplicar a fila e os limites de leitura desde a primeira chamada, sem depender
   de uma resposta prematura. Preservar a possibilidade de uma solicitação de
   mudanças fundamentada antes de ler todo o escopo de aprovação.
2. Acrescentar provas offline e Docker/ACP com ferramentas desde a primeira
   resposta, páginas múltiplas e compactação real. Manter a cobertura integral
   exigida para aprovação e o orçamento de 40 iterações.
3. Instalar a correção qualificada sob manutenção e registrar recuperação
   vinculada à nova condição. Só então executar outra revisão nativa,
   preservando o bloqueio atual e exigindo leituras próprias da sucessora.
4. Comprovar revisão e congelamento, Green, controles negativos, revisão da
   entrega, PR/CI e implantação/QA/rollback no mesmo commit sob o contrato v2.
5. Demonstrar diagnóstico e recuperação por Tech Lead/CTO, novo brief com cards
   dependentes e memória entre perfis, sem condução do operador.
6. Qualificar instalação limpa e reutilização por terceiros antes de apresentar
   a plataforma como pronta. A fatia inicial do Truco não encerrará sua v0.1.

O adaptador de recuperação de inspeção falha foi instalado e seu registro foi
exercitado antes da última revisão. Ele exige erro nativo preservado,
RPCs sem duplicação, leituras parciais válidas, lease fechada, worker retirado,
outro worker qualificado e manutenção selada. A causa do erro genérico permanece
explicitamente não comprovada. O registro não despacha modelo, não herda leituras
como aprovação e não encerra o incidente. Um parecer novo e independente continua
obrigatório. O registro e o despacho da sucessora funcionaram; a revisão voltou
a bloquear. Isso não comprova recuperação integral nem diagnóstico ou
replanejamento universalmente autônomos pelo CTO.

## Navegação

- [Arquitetura e fronteiras de autoridade](ARCHITECTURE.md)
- [Validação atual e evidências históricas](VALIDATION.md)
- [Critérios objetivos e trabalho restante](ROADMAP.md)
- [Instalação segura](SETUP.md)
- [Recuperação de QA e revisão](QA-PROTOCOL-RECOVERY.md)
- [Limites dos recibos de patch](PATCH-RECEIPTS.md)
