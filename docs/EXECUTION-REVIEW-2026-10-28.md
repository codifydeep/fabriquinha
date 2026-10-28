# Balanço crítico e plano proposto — 28 de outubro de 2026

**Auditoria originalmente produzida durante a pausa.** O proprietário aprovou
o plano e os refinamentos posteriormente em 28/10 e solicitou continuidade,
mantendo o modelo atual. Ver [ADR 0007](ADR-0007-EVIDENCE-BASED-SUCCESSION.md).
O retrato auditado abaixo permanece histórico; aprovação não equivale a instalação. Fonte examinada: `fc202f3a`; runtime instalado: `8d6bbd92`.
Supervisor descarregado, relay parado, política desabilitada e pausa persistente
conferidos. Nenhuma chamada ao modelo, ensaio de produto, alteração de card ou
reclassificação de entrega foi feita nesta auditoria. Foram lidos código,
documentos, Kanban/recibos privados e metadados de consumo do relay parado.
Os dados privados completos continuam fora do Git.

## Parecer

**Manter Hermes + Kanban. A simplificação de plataforma funcionou parcialmente;
a estratégia de recuperação ainda precisa mudar.** Temos uma entrega S4 técnica
sem intervenção e uma continuidade S5 homologada com assistência. S6 integrou
o primeiro incremento e travou no segundo. Não é correto chamar isso de ausência
de progresso, nem de autonomia quase concluída.

O controlador impede várias classes de falsa conclusão, mas uma situação normal
— teste derivado incorreto ou parecer técnico equivocado — ainda pode exigir
modificar a própria plataforma. Temos boa proteção do histórico, mas continuidade
insuficiente diante de evidência nova. O próximo investimento deve ser permitir
que os agentes resolvam esses casos por operações existentes e explícitas,
sem mais uma recuperação especializada por incidente.

Não recomendo trocar plataforma/modelo, adicionar agentes ou reiniciar o produto.
Também não recomendo simplesmente aumentar tentativas ou instalar a última mudança
de prompt e repetir o ciclo. O último reparo melhora uma orientação; não fecha
o caminho de saída da triagem nem comprova que o CTO formulará o diagnóstico certo.

## Percentuais e método

Estimativas de engenharia para a prontidão **no escopo já perseguido: um host,
GitHub, Python/HTTP web local e uma release ativa**. Não são probabilidade de
sucesso, porcentagem de horas restantes ou capacidade de desenvolver qualquer
SaaS/mobile/3D. Usar esta régua como referência futura, sem elevar números por
quantidade de commits, linhas, testes internos ou cards encerrados.

| Dimensão | Peso | Prontidão estimada | Evidência e lacuna dominante |
|---|---:|---:|---|
| Cadeia de entrega técnica | 20% | 85% | S4 completo; S5 assistido; falta repetibilidade no problema S6 |
| TDD, regressão e revisão | 20% | 85% | Red/freeze/Green/controles/CI/QA reais; revisão semântica e correção de teste ainda frágeis |
| Recuperação autônoma | 25% | 40% | Diagnóstico e retomada funcionam em casos delimitados; triagem e pareceres equivocados ainda exigem operador |
| Continuidade e memória entre incrementos | 15% | 65% | S5 em dois pacotes; S6 liberou dependência; história técnica pode induzir bloqueio repetido |
| Canal do CEO e comunicação operacional | 10% | 20% | Intake CLI e outbox; Telegram completo não configurado/qualificado nesta instalação |
| Instalação, operação e recuperação por terceiros | 10% | 50% | Fonte pública/pins/doctor e provas locais; restore operacional e reprodução externa incompletos |

Média ponderada: 60,75%; comunicar **aproximadamente 60%**, com incerteza de ao
menos dez pontos. O indicador limita-se ao escopo acima. Não implica que 40% do
tempo ou dinheiro resolverá o restante. A recuperação é um gargalo: vários
componentes em 85% não compensam um fluxo que termina em triagem sem ação.

Não há série anterior consistente com estes pesos que permita calcular uma
queda percentual rigorosa. Estimativas antigas baseadas em infraestrutura ou
etapas implementadas não devem ser comparadas como se fossem a mesma medida.
As provas S4/S5 continuam válidas no seu escopo; S6 revela limites, não apaga
essas provas. Uma taxa empírica de autonomia precisa de execuções comparáveis;
os ensaios atuais são heterogêneos e insuficientes para essa estatística.

## Evolução do plano aprovado

| Marco | Balanço |
|---|---|
| S0/S1, retirar coordenação duplicada | Cumprido na fronteira qualificada; Hermes upstream não foi modificado |
| S2/S3, qualidade e entrega determinísticas | Funcionam em entregas reais; não são mais apenas mocks |
| S4, primeira homologação sem condução técnica externa | Qualificada com brief reutilizado sob autorização; não prova descoberta arbitrária |
| S5, continuidade | Homologada, dois pacotes e regressão; sete intervenções preservadas impedem alegar ciclo limpo |
| S6, outro projeto/operação/distribuição | Parcial: primeiro incremento homologado tecnicamente; segundo em triagem; canal e restore pendentes |
| S7, Truco completo e ampliação | Não liberado por este caminho; lobby S6 não é o produto Truco inteiro |

Foi acertado unificar a aceitação de navegador entre prévia e deploy. Isso removeu
uma linguagem JSON própria incapaz de expressar duas sessões e o prazo do brief.
Foi acertado restaurar o feedback de validação ao implementador, separar revisão
de escrita e fixar a fonte e o bundle de qualidade. O mesmo cuidado não foi
aplicado suficientemente cedo ao caminho completo de manutenção dos testes.

O plano de 24/10 já alertava para recuperações por caso. Ainda assim, depois de
S5 cresceram protocolos de submissão, revisão de fixture, substituição da cauda
do grafo e compatibilidades de fase. A execução preservou integridade, mas não
cumpriu plenamente a intenção de reduzir responsabilidades do código próprio.

## Por que os bloqueios continuam

### 1. A revisão aceita um Red sem reconhecer a razão errada da falha

O gate verifica falha de asserção em caso novo, base preservada e descoberta
completa. Isso é necessário, mas não prova que a falha representa o comportamento
pretendido. Um teste novo buscava uma sala sem criá-la. O defeito atravessou a
revisão/freeze e só foi explicitado quando a implementação avançou.

No primeiro Red, a ausência geral da interface pode mascarar defeitos posteriores
da fixture. Não se deve exigir Green antes da implementação nem simular produto
para provar tudo antecipadamente. A revisão precisa inspecionar a preparação,
a ação e a asserção e registrar o motivo esperado do Red. Falhas de preparação
na mesma linha de asserção não viram comportamento correto por serem vermelhas.

Isso recomenda melhorar a revisão e permitir revisão controlada de testes,
não inventar um verificador universal da intenção de Python.

### 2. Imutabilidade da evidência virou, em alguns caminhos, rigidez do processo

Snapshots antigos devem permanecer imutáveis. Isso não exige tratar a expectativa
tecnicamente errada como obrigação permanente. A autoridade para correções
justificadas já foi delegada no ADR 0004/0006, mas a implementação admite apenas
formatos muito estreitos. O comparador de fixture inicialmente recusou chamadas
importadas e blocos `with` necessários para a própria preparação aprovada.

O comparador AST é evidência estrutural, não prova de equivalência semântica.
Seu próprio contrato reconhece efeitos colaterais de chamadas existentes.
Expandir indefinidamente uma linguagem permitida de alterações cria um compilador
parcial de políticas sem eliminar a necessidade de revisão independente.

É necessário distinguir: testes de uma entrega já integrada; testes candidatos
congelados apenas para revisão; e a versão nova, revisada, que os substitui.
Proteger a baseline entregue deve continuar obrigatório. A revisão de candidato
não publicado deve ter um fluxo normal, com diff, justificativa, identidade
independente e todos os gates. Ampliar as mudanças hoje admitidas exige aprovação
explícita da política correspondente; esta auditoria não o faz.

### 3. O diagnóstico está executando um experimento que não responde à hipótese

Na revisão atual, o novo Red executou 16 casos, com sete falhas comportamentais,
nenhum erro e nenhum skip. Os diagnósticos seguintes rodam a base anterior à
implementação: não há interface de entrada na sala, e o teste para antes do
ponto discutido. Repetir esse experimento demonstra a mesma ausência de produto;
não demonstra que duas asserções posteriores sejam incompatíveis.

O teste exige HTTP 409 numa chamada Python separada. O CTO inferiu que o navegador
obrigatoriamente receberia o mesmo 409 e emitiria erro de console. O experimento
genérico preservado demonstrou o contrário: 409 em Python não produz evento no
console do navegador; um fetch do navegador recebendo 409 produz o evento.
Isso não comprova a implementação nem resolve uma corrida entre clientes. Uma
pré-checagem pode atender à ordem do teste, mas não substitui rejeição atômica
no servidor quando há concorrência. Essa distinção precisa ser decidida pela
engenharia, não pelo CEO.

Mesmo que o produto atual emita 409 no navegador, isso seria um dado da
implementação observada; não uma exigência inevitável do teste. Por outro lado,
proibir todo `console.error`, inclusive resposta de negócio esperada, merece
revisão separada: é uma política potencialmente mais forte que ausência de erro
funcional. Não propor remover o teste ou filtrar mensagens amplamente para passar.
Se a equipe justificar outra classificação, ela precisa de regra precisa,
observabilidade preservada, aprovação do contrato e nova evidência.

### 4. Existe escalonamento de papel, mas falta fechamento da decisão

O CTO escreveu que o caso precisava de uma decisão do CTO e retomou a exigência
de aceite do CEO para uma questão técnica. Na sequência, manteve hold. Receber
um papel no prompt não garante exercer sua autoridade. O contrato deve pedir
uma decisão executável, com a evidência que a sustenta e a operação permitida.

Além disso, a retomada de `recovery.py` aceita fonte `blocked`, mas não `triage`.
Isso protege o breaker. As saídas de triagem dependem de protocolos específicos
em `repairs.py`, com limites de profundidade. A atual revisão de testes não tem
uma saída qualificada apenas por instalar a orientação nova. Um `next_action`
em texto pode descrever uma operação que a plataforma não oferece.

Não remover o breaker. Introduzir uma única forma limitada de sucessão após
nova evidência revisada, preservando o card/decisão antigos, é preferível a
acrescentar mais um número de protocolo para cada nova exceção. Reusar os cards,
o journal e a substituição já existentes; não criar outro motor de workflow.

### 5. Testes programados comprovam mecanismos, não julgamento

Os 446 testes do núcleo e as provas nativas são úteis. Entretanto, os participantes
programados sabem qual ferramenta, decisão e transição produzir. Não exercitam
bem inferências equivocadas, uma decisão que pede a si própria uma decisão,
confusão entre início e conclusão ou contexto contraditório após handoff.

A próxima qualificação deve combinar testes determinísticos de identidade,
reinício e idempotência com um pequeno conjunto de casos semânticos preservados.
Medir decisão sustentada por evidência e ação seguinte válida. Mais um teste
que apenas confirma a presença de uma frase no prompt não demonstra correção.

### 6. O estado documental e o contexto têm mensagens concorrentes

O STATUS dizia, simultaneamente, que havia novo Red e que ele ainda não existia;
também dizia que supervisor/relay estavam ativos após a pausa. Esses trechos
foram corrigidos nesta auditoria. Documentos históricos extensos permanecem úteis
como referência, mas não devem integrar o contexto padrão dos agentes.

O SDK opera com `skip_memory=True` e `skip_context_files=True`. A continuidade
qualificada usa sessões e artefatos/recibos explicitamente selecionados; não é
uma memória organizacional livre aprendendo automaticamente. Isso ajuda o
isolamento, mas exige separar fato atual, hipótese, decisão válida e orientação
histórica superada. S5 já mostrou ancoragem em um hold antigo. Banco vetorial ou
mais conversa no Telegram não resolve essa distinção.

## A execução está correta?

**Correta na preservação de integridade; insuficiente na economia do processo.**

Preservar: revisão sem escrita, testes completos, source/SHA exatos, isolamento,
PR/CI independente, rollback, pausa e contador duráveis, recusa de homologação
fictícia. Não houve conversão dos bloqueios em sucesso para melhorar indicadores.

Corrigir na condução: continuamos ajustando o controlador depois de cada ensaio;
algumas correções estreitas criaram novos bloqueios. A separação entre autoria,
revisão e diagnóstico foi boa, mas os caminhos alternativos não receberam a mesma
atenção que o caminho feliz. O orçamento de complexidade não foi mantido.

Contagem física de fontes versionadas, excluindo testes e scripts:

| Checkpoint | Módulos em `src/fabriquinha` | Linhas |
|---|---:|---:|
| `e7349bb6`, checkpoint S5 | 21 | 6.689 |
| `000b5c5a`, auditoria pré-S6 | 24 | 7.227 |
| `fc202f3a`, atual | 25 | 8.389 |

Crescimento desde S5: aproximadamente 25%. A meta inicial era cerca de 3.000
linhas/12 módulos; não era um limite de segurança, mas foi excedida amplamente.
Parte do aumento é justificada por isolamento e entrega real. A contagem sozinha
não exige cortar código bom nem minificar; exige parar a expansão sem retirada
correspondente de caminhos concorrentes. O legado preservado soma 1.947 arquivos;
não está todo ativo. Não confundir arquivo histórico com serviço em execução.

O controller nativo continua substancialmente menor que o broker antigo de
60 mil linhas, e a entrega S4 é um ganho concreto. Não há evidência para concluir
que reintroduzir Multica ou Temporal corrigiria o julgamento técnico observado.

## Custos e oportunidades

Janela S6, chamadas 6.952–7.247: 296 registros distintos, todos vinculados ao
projeto/atividade; US$ 1,2739285 reportados, nenhum custo ausente nessa janela.
São metadados recebidos, não uma reconciliação da fatura e nem o gasto histórico
do projeto. Contador atual 7.247/8.500; 1.253 chamadas remanescentes. A pausa não
resetou limite ou histórico.

| Atividade | Chamadas | Custo reportado USD |
|---|---:|---:|
| Brief | 2 | 0,0046951 |
| Planejamento e revisão de planos | 25 | 0,0858026 |
| Autoria de testes | 61 | 0,2580490 |
| Revisão de testes | 19 | 0,0805128 |
| Implementação | 133 | 0,7197566 |
| Diagnóstico | 54 | 0,1160072 |
| Revisão de implementação | 2 | 0,0091052 |

8.720.865 tokens de entrada e 803.684 de saída contabilizados; 466.783 de
raciocínio são parte da saída, não devem ser somados novamente. Cache lido/escrito
foi reportado como zero. Integração determinística não requer chamadas próprias.
O custo do assistente operador, máquina e tempo humano não está nessa tabela.

A prioridade econômica é evitar retrabalho, não baixar alguns centavos trocando
modelo. Diagnóstico consumiu cerca de 18% das chamadas; não é todo desperdício,
mas os experimentos repetidos que não alcançam a hipótese não acrescentam prova.
A implementação representa cerca de 57% do valor reportado e precisa de feedback
curto e útil, sem redescobrir o contrato e os arquivos a cada tentativa.

Medidas propostas:

1. Pacote de contexto pequeno: objetivo, base exata, diff atual, testes relevantes,
   falha observada e decisões válidas. História completa sob consulta. Não cortar
   a suíte executada; reduzir o que precisa atravessar o modelo repetidamente.
2. Usar a mesma evidência de job para o mesmo snapshot/fase/validador quando o
   contrato já permitir; não executar outra suíte idêntica só para obter um novo
   texto de diagnóstico. Nova versão ou nova hipótese executável exige nova prova.
   Não reutilizar aprovações entre SHAs nem presumir equivalência de ambientes.
3. Manter o limite de saída atual como teto, não meta. Só testar caps por papel
   com os casos preservados; reduzir tudo para 8k agora pode recriar truncamentos.
4. Examinar caching explicitamente apenas depois de estabilizar os prompts.
   OpenRouter documenta prefixos reutilizáveis, requisitos por provedor e campos
   de cache. Nenhum percentual de economia é prometido sem experimento medido.
5. Um resumo de custo por incremento/recuperação, derivado do ledger existente,
   em vez de novo dashboard/serviço. Separar conhecido, desconhecido e custo do
   operador. Não tratar teto de chamadas como teto financeiro.
6. Preservar papéis, mas ativar especialistas sob demanda. Fluxo normal: produto
   no escopo, autor e revisor independentes, execução de integração determinística.
   CTO intervém na ambiguidade técnica; não revisa duas vezes toda decisão rotineira.
7. Considerar modelo distinto para uma decisão técnica difícil somente se o corpus
   mostrar ganho de decisões corretas por custo. Perfis do mesmo modelo compartilham
   vieses; mais um parecer do mesmo modelo não é garantia de independência cognitiva.
   Não alterar rotas/fallback nesta auditoria.

## Plano revisado para execução posterior

### P0 — Fixar a referência e eliminar contexto contraditório

Preservar pausa, brief, primeiro incremento e incidentes. Usar STATUS como entrada
atual, esta auditoria como proposta e ADRs como autoridade. Separar hipóteses de
observações nos handoffs. Manter o patch `fc202f3a` como publicado/não instalado.

Saída: pacote legível do caso atual, com cliente HTTP, ordem dos eventos, fase,
assertion atingida ou não, fonte e operação seguinte disponível. Sem chamada paga.
Não alterar produto ou teste para tornar o caso mais conveniente.

### P1 — Fechar uma recuperação reutilizável, antes de repetir S6

Reusar `Recovery`/`Repairs` e o Kanban. Definir uma proposta de sucessão técnica
que abranja revisão contestada e correção autorizada de candidato ainda não
publicado. Sem novo banco, serviço, catálogo por incidente ou reset de triagem.

Pré-condições: origem/execução exatas, incidente/parecer preservados, ausência de
leases/efeitos pendentes, evidência nova identificada, escopo claro e decisão
independente. Se não houver evidência nova, não despachar de novo. Limites devem
bloquear repetição da mesma hipótese, não proibir todo progresso após correção.

Saída: operação executável e idempotente para retomar revisão ou gerar revisão
sucessora, sem implementar o produto ou aprovar a entrega. Preservar fonte antiga
como histórica. Se apenas uma nova variante de protocolo for necessária por
incidente, reconsiderar o desenho antes de codificar.

Não confundir prompt novo com evidência nova. A prova HTTP é um fato limitado;
a correção do comparador/fase é uma pré-condição operacional diferente. Devem
estar identificados, e o CTO precisa reavaliar, sem receber aprovação pronta.

### P2 — Normalizar o ciclo dos testes sem enfraquecer regressão

Tratar testes novos ainda não integrados como candidatos versionados. Uma revisão
corrigida precisa de justificativa pelo brief, diff completo, revisão independente,
Red apropriado, controles pertinentes e todos os gates finais. A baseline entregue
continua protegida. Mudança de negócio/remover cobertura continua com CEO.

Proposta de simplificação sujeita a aceite antes de mudar o gate: substituir a
restrição sintática universal de fixture por escopo de revisão explicitamente
autorizado e análise independente; manter o comparador como relatório auxiliar.
Não tentar provar equivalência semântica por AST. Uma nova importação ou helper
legítimo não deve exigir mudar a plataforma. Testes removidos, skips, descoberta
parcial e troca silenciosa de baseline continuam bloqueados por padrão.

Revisão do Red deve explicar preparação/ação/asserção e por que a falha é esperada.
Não aumentar burocracia com mais um agente. Corrigir o foco da revisão existente.
A discussão sobre console HTTP esperado é outra decisão de política; não é
condição automática para o conserto atual nem deve ser resolvida por whitelist vaga.

### P3 — Qualificar a recuperação como comportamento, não só transição

Antes de despacho pago: casos offline de hipótese sem evidência; experimento que
não alcança a asserção; triagem com evidência realmente nova; parecer obsoleto;
interrupção entre criação da sucessora e vínculo; tentativa de autocertificação
ou enfraquecimento dos testes. Nenhuma duplicação, aprovação implícita ou reset.

Depois da retomada autorizada, corpus curto com decisões reais dos agentes,
usando os artefatos preservados. Critérios: distinguir cliente Python/navegador;
reconhecer Red esperado; CTO decidir a questão técnica; indicar operação realmente
permitida. Não orientar o resultado por uma solução de produto fornecida pelo
operador. Uma resposta convincente sem ferramenta terminal não é sucesso.

### P4 — Concluir o S6 existente, sem outro ensaio genérico

A equipe resolve a revisão, implementa o segundo incremento e passa pela mesma
suíte, controles, revisão, PR/CI, deploy, rollback e QA. Preservar primeiro
incremento. Registrar o resultado como assistido se houver intervenção; não
transformar o ciclo atual em prova limpa retroativamente.

Saída: todos os critérios do brief S6 no SHA implantado. Não construir 3D/mobile,
analytics nem outro produto antes dessa saída. Não basta dizer que o worker voltou.

### P5 — Fechar o contrato com o usuário e a operação pública

Qualificar um canal real de ponta a ponta: entrada, pergunta objetiva, resposta
vinculada e entrega. Reusar intake/outbox; transporte não coordena outro workflow.
Qualificar restauração/upgrade/rollback da instalação isolada, com contador e
pausa preservados, e reprodução a partir do clone/documentação públicos.

Remover dependências do legado da entrada distribuída depois de verificar os
imports e recursos ainda necessários. História continua no Git/arquivos de
recuperação. Não remover backups ou serviços nesta auditoria.

### P6 — Demonstrar autonomia delimitada, com denominador explícito

Uma nova versão útil do mesmo produto, dois incrementos dependentes e uma falha
controlada recuperável, sem patch no controlador, edição manual do produto ou
passos técnicos conduzidos pelo operador após aceite. CEO responde apenas escopo.
Repetir uma segunda entrega comparável antes de alegar repetibilidade; uma única
prova comprova viabilidade, não confiabilidade estatística geral.

Publicar: entregas completas/execuções iniciadas; intervenções externas; incidentes
recuperados/recuperáveis; tempo parado sem ação; chamadas/custo conhecido; revisões
de testes; commits implantados. Mostrar também pausas e dependências externas,
sem contá-las como falha de produto. Separar encerramento de atividade e da release.

## Guardas contra outra espiral de complexidade

- Não criar novo serviço, banco, orquestrador ou personagem para corrigir estes casos.
- Preferir substituir protocolos concorrentes, não adicionar outro sem retirada.
- Uma exceção não deve exigir transportar toda a história para o próximo agente.
- Não repetir uma hipótese sem observação relevante nova ou experimento diferente.
- Não aceitar sucesso escrito nem enfraquecer a qualidade para aumentar a taxa.
- Não prometer ausência universal de starvation: credenciais, saldo e decisões
  externas podem bloquear legitimamente. Prometer ausência de limbo silencioso,
  responsável e ação executável para falhas internas suportadas.
- Se a próxima recuperação ordinária ainda exigir modificar a plataforma, parar
  a expansão de produto e revisar a operação de correção; não aumentar apenas o teto.

## Referências e limites da auditoria

### Avaliação semântica antes da migração

Cinco chamadas isoladas ao mesmo Claude Haiku consumiram os números 7.248–7.252.
Quatro decisões passaram: distinção de clientes HTTP, hipótese não alcançada,
ausência de evidência nova e teste enfraquecido. O caso de Red esperado falhou:
o raciocínio reconheceu a fase, mas a operação selecionada pediu mudanças sem
defeito concreto. Não houve ferramentas de workspace, alteração de card nem
aprovação de entrega. O resultado original permanece não aprovado.

Limitação metodológica: o primeiro ensaio usou instrução genérica, sem os
contratos completos da revisão instalada. A avaliação seguinte deve importar
esses contratos diretamente, sem incluir os gabaritos. A orientação compartilhada
foi esclarecida: inspecionar primeiro; Red esperado não constitui defeito nem
aprovação; devolução requer defeito observado. Não se deve inferir autonomia
a partir de cinco respostas isoladas, mesmo que a repetição passe.

Migração permanece preparada, não concluída: fonte `db0c3d3d` exportada e doctor
aprovado, backup SQLite restaurado em memória, zero execuções abertas. O relay
foi desabilitado e parado após a avaliação. A correção de contexto ainda exige
nova fonte congelada antes de instalar e retomar o S6.

Código: `quality.py` (Red/receipts), `test_revision.py` (comparador), `repairs.py`
(sucessão limitada), `recovery.py` (blocked/triage/decisões), `hermes.py`
(contexto/skip_memory), `provider.py` (metadados reportados).

Documentos: [plano 24/10](SIMPLIFICATION-REVIEW-2026-10-24.md),
[auditoria 27/10](EXECUTION-REVIEW-2026-10-27.md),
[S4](HERMES-S4-QUALIFICATION.md), [S5](HERMES-S5-QUALIFICATION.md),
[prova HTTP](S6-HTTP-CLIENT-DIAGNOSIS.md), [status](STATUS.md).

Fontes oficiais consultadas para as recomendações: [Playwright, comportamento
visível e isolamento](https://playwright.dev/docs/best-practices),
[pytest, preparação por fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html),
[OpenRouter, caching e metadados](https://openrouter.ai/docs/guides/best-practices/prompt-caching).
Não é proposta de migração para pytest, nem garantia de desconto na rota atual.

Os 446 testes e o experimento HTTP são resultados previamente executados, não
reexecuções feitas durante esta auditoria. Não foi feita varredura completa de
segurança nem teste adversarial de todos os handlers. As conclusões de autonomia
baseiam-se no fluxo observado e nos caminhos de código examinados.
