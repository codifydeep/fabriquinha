# Balanço crítico e plano — 30/10/2026

## Parecer

A v0.3 comprova uma entrega real de dois incrementos dependentes, com recuperação
pela própria equipe após o aceite. O caminho Hermes + Kanban merece ser mantido.
A prioridade deixa de ser construir mecanismos em antecipação a todo incidente:
passa a ser repetir entregas úteis, medir confiabilidade e reduzir duplicações.
Não trocar modelo, adicionar orquestrador ou reiniciar o projeto.

A qualificação é delimitada: Python/HTTP, navegador, memória local, um host, uma
release ativa e GitHub. Não prova autonomia geral para qualquer SaaS, mobile ou
3D, nem instalação por terceiros. A proposta e a divisão inicial em dois
incrementos foram orientadas pelo operador antes do brief; portanto o ciclo
não mede descoberta completamente aberta a partir de uma ideia vaga.

## Evidência conferida

- Release v0.3: `HOMOLOGADA`; PRs [16](https://github.com/codifydeep/descartavel/pull/16)
  e [17](https://github.com/codifydeep/descartavel/pull/17).
- Incremento 1: commit `578a77b5cde84986c9bf4f7a792e8d8622454524`;
  25 casos na suíte. Incremento 2: `26ee2774a689bfd5b21888d42ec41375c5db6d10`;
  30 casos na suíte e 28 casos de navegador no QA implantado.
- URL vigente na conferência: http://127.0.0.1:61323. `/identity` confirmou o
  commit final. CI obrigatória `fabriquinha-local-ci` no mesmo commit.
- Dois congelamentos independentes, dois Greens, seis e quatro jobs de controles
  negativos respectivamente, duas revisões de implementação e dois QAs.
- Cada incremento passou por implantação, rollback e restauração.
- Todos os 11 arquivos da pasta de testes da v0.2 (casos e manifestos) existem
  na entrega final e são byte a byte idênticos. O segundo Red usa a entrega
  aprovada do primeiro incremento como baseline.
- CTO solicitou correção do plano; Tech Lead revisou e CTO aprovou.
- Um worker de QA encerrou sem operação terminal após recusas de validação.
  Tech Lead executou diagnóstico, comprovou Red comportamental válido e retomou
  a autoria. O mesmo fluxo chegou ao freeze e à entrega sem correção da plataforma.
- 26 registros de execução, incluindo aceite e fechamento determinísticos;
  cinco esperas de integração são estados persistentes normais, não cinco falhas.
- Aproximadamente 65 minutos entre aceite e fechamento; 15 atividades com modelo.
- Relay atribuiu 82 chamadas à release e US$ 0,3758524, com custo informado em
  todas. Inclui elaboração do brief. São custos reportados pelo provedor, não
  auditoria de cobrança; infraestrutura local e trabalho do operador não entram.
- Consumo global observado: 7.485 chamadas; teto autorizado 8.500.

A leitura dos registros e do histórico desta conversa não encontrou intervenção
operacional depois do aceite: nenhum ajuste manual de card, teste ou workspace,
nenhum novo código de controlador instalado. Isso sustenta a classificação
**execução autônoma observada neste ciclo**, sem garantir inviolabilidade forense
contra mudanças externas não registradas. A v0.2 continua assistida. Não alterar
recibos históricos nem confundir o campo técnico `qualification=false` (execução
real fora de fixture) com ausência de homologação: a aprovação está no recibo
controlador de aceitação e em seu estado `HOMOLOGADA`.

## Prontidão estimada com a mesma régua de 28/10

| Dimensão | Peso | Estimativa | Limite ainda relevante |
|---|---:|---:|---|
| Cadeia de entrega | 20% | 95% | Repetibilidade em outras mudanças |
| TDD, regressão e revisão | 20% | 90% | Julgamento semântico e qualidade das fixtures |
| Recuperação autônoma | 25% | 75% | Recuperou handoff; não todas as falhas externas |
| Continuidade e memória | 15% | 85% | Baseline entre incrementos, não meses de evolução |
| Canal e comunicação | 10% | 85% | Entrada/aceite/avisos reais; leitura operacional confusa |
| Operação e distribuição | 10% | 60% | Falta instalação independente e restore operacional |

Média ponderada 83%; comunicar **80–85% no escopo restrito**, com incerteza de
aproximadamente dez pontos. Não é percentual de tempo restante, taxa de sucesso
ou prontidão do Truco completo. O ganho desde os ~60% de 28/10 vem da recuperação,
continuidade e canal agora observados. Uma release não permite estimar uma taxa
confiável de sucesso. Contar entregas comparáveis; não misturar ensaios assistidos.

## Crítica da execução

O desenho está funcionando melhor porque transferências são persistentes,
revisão não escreve a entrega e integrações não dependem de conversa entre bots.
A autonomia inclui diagnosticar um erro e retomar; não exige ausência de erros.
O bloqueio de QA desta vez não virou limbo. A aprovação de plano pelo CTO teve
valor concreto: corrigiu critério omitido e responsabilidade ambígua.

Há quatro limites que merecem ação, sem expandir a arquitetura:

1. **Documentação conflitante.** README e roadmap ainda anunciavam entrada
   Telegram pendente e S6 incompleto. Isso aumenta desorientação e pode contaminar
   contexto dos agentes. Status corrente deve ser curto; auditorias antigas
   devem permanecer explicitamente históricas.
2. **Painel não interpreta a governança.** Mostra cartões substituídos como
   bloqueados/todo, `Orchestration: Auto` e `Gateway: Off` de mecanismos nativos
   diferentes do controlador atual. O painel de consulta foi útil, mas ainda
   exige leitura técnica. Não habilitar edição direta para contornar isso.
3. **Promessas textuais de revisão.** O parecer do plano menciona cadeias de
   sign-off backend/frontend/CTO, enquanto as execuções comprovam a revisão
   de implementação pelo Tech Lead e arquitetura pelo CTO. A independência
   prevista pelo controlador foi cumprida; a frase sugere mais assinaturas do
   que o fluxo registra. Adotar uma matriz executável única e impedir que o
   plano prometa gates adicionais sem representá-los. Não adicionar revisores
   só para fazer a implementação corresponder a uma frase excessiva.
4. **Fixtures repetem mecanismos.** Os arquivos `acceptance_h_ready_mark.py`
   e `acceptance_i_ready_to_play.py` concatenam `creator_errors + joiner_errors`
   no setup e depois verificam a cópia. Erros posteriores não entram nessa
   cópia. Porém `AcceptanceTest.new_context` registra console/pageerror na lista
   central e `acceptance_evaluate` reprova qualquer erro, preservando a proteção.
   É redundância defeituosa local, não evidência de erro escapando na entrega.
   Simplificar em alteração revisada e comprovar com injeção negativa que um
   erro após o setup continua reprovando. Não editar snapshots ou reduzir gates.

O núcleo próprio ainda soma aproximadamente 9,7 mil linhas Python. A remoção do
Multica reduziu dependências operacionais, mas não tornou o controlador pequeno.
Evitar nova recuperação especializada por toda falha de agente; primeiro usar
classificação, diagnóstico e retomada existentes. Compatibilidade histórica deve
ser isolada e testada antes de qualquer remoção, nunca apagada em lote.

## TDD e memória

Red, revisão/freeze, implementação, Green, controles, revisão e QA ocorreram na
ordem esperada. Arquivos e inventários preservados oferecem uma base concreta de
regressão. Quantidade de assertions ou testes não comprova intenção; a inspeção
da cópia de erros demonstra por que revisão semântica continua necessária.

A memória mais confiável demonstrada foi artefactual: brief aprovado, plano,
baseline do incremento anterior, testes, diagnósticos e commits. Manter esse
modelo; não introduzir banco vetorial para resolver um problema ainda não medido.
Um resumo curto de decisões vigentes com links às evidências é preferível a
reenviar todo o histórico. Decisões substituídas devem ficar fora do contexto
ativo, preservadas para auditoria. A leitura efetuada não constitui auditoria
completa de todos os mecanismos de memória do Hermes.

## Custo e simplificação

US$ 0,376 por este ciclo não justifica trocar o modelo agora. O primeiro worker
QA consumiu 18 chamadas de relay antes do bloqueio (o SDK relatou 16); os sistemas
contam camadas diferentes. Diagnóstico e retomada consumiram mais sete chamadas.
Isso aponta oportunidade de feedback mais claro sobre como concluir a submissão,
não autorização para promover texto em operação terminal ou aumentar retries.

- Medir chamadas, custo, duração e recusas por fase a partir dos recibos atuais.
- Reutilizar validação determinística somente quando snapshot, bundle, fase e
  contexto exigidos forem idênticos; CI do commit integrado e QA implantado têm
  identidades distintas e não podem ser eliminados como mera duplicação.
- Manter os nove perfis configurados; convocar só os relevantes. Não exigir
  participação de Designer/Mobile/Dados numa mudança pequena de lobby.
- Manter uma cadeia normal de revisão independente; CTO revisa arquitetura e
  trata escalonamentos. Mais assinaturas não implicam melhor qualidade.
- Compactar o contexto para evidência atual e última recusa. Medir antes de
  prometer economia percentual.
- Arquivar visualmente os predecessores substituídos através de uma visão
  derivada, sem mudar sua história para `done` ou excluir provas.

## Plano proposto, em ordem

### P0 — Consolidar o marco (esta auditoria)

Atualizar status, README e roadmap; manter v0.3 e fonte instalada intactas.
Publicar o escopo comprovado e os limites. Não iniciar outro ciclo pago nesta
análise. Saída: documentação sem afirmações correntes contraditórias.

### P1 — Higiene pequena antes de ampliar escopo

Responsáveis: Tech Lead/QA para fixtures; mantenedor da plataforma para a visão.
Abrir reparo delimitado da duplicação de observadores pela governança existente,
com teste negativo de erro JavaScript após setup e suíte integral preservada.
Alinhar a redação de planejamento com a matriz executável de revisão; não mudar
quem aprova nem remover revisão independente. Exibir estado da release, URL,
responsável, último progresso e predecessor substituído usando dados existentes.
Saída: sem nova tabela, serviço ou protocolo de coordenação; provas de leitura
não alteram cards, e observadores continuam detectando a falha injetada.

### P2 — Próxima entrega útil, sem novo ensaio genérico

Proposta de produto: iniciar o motor determinístico de regras do Truco Paulista,
antes de acrescentar 3D. Produto deve esclarecer variante e casos ambíguos com o
CEO; CTO escolhe desenho técnico. Manter escopo pequeno e dois incrementos com
valor verificável, definidos pelo time, não previamente roteirizados pelo operador.
O objetivo concreto e o brief precisam de aceite; este documento não os aprova.
Saída: segunda entrega comparável do aceite à homologação, sem intervenção,
com regressões anteriores passando. Qualquer reparo externo reclassifica apenas
aquele ciclo como assistido, preservando a prova v0.3.

### P3 — Resiliência operacional delimitada

Após a segunda entrega, executar uma janela controlada de interrupção do
supervisor durante uma operação com efeito externo em instalação de teste.
Usar os mecanismos existentes de pausa/retomada e reconciliação. Confirmar um
único PR/merge/deploy efetivo, nenhuma chamada incerta repetida cegamente, contador
preservado e aviso útil. Depois restaurar backup numa instalação isolada e
reconciliar evidências/efeitos, sem ativar duas instâncias que escrevam no mesmo
projeto. Saída: recuperação comprovada, não apenas banco legível ou processo vivo.

### P4 — Reutilização por outra pessoa

Instalar a mesma fonte em ambiente limpo e repositório descartável diferente,
seguindo exclusivamente a documentação. Credenciais por instalação, sem caminhos
pessoais embutidos. Outra pessoa deve conseguir propor, aprovar, acompanhar e
abrir a homologação sem orientação privada do autor. Repetir entrega pequena,
registrar custos e testar desligamento/retomada. Saída: instruções reproduzíveis
sem acesso aos diretórios privados desta instalação.

### P5 — Ampliar capacidades com produto real

Introduzir domínio mais complexo, frontend/3D, persistência e mobile em fases
separadas, com validadores e critérios apropriados. Não extrapolar o executor
Python/HTTP para stacks ainda não qualificadas. Observabilidade de produto e
experimentos entram quando houver perguntas e métricas úteis definidas, evitando
criar papéis sem demanda. Não condicionar o início do desenvolvimento útil à
perfeição de todas essas capacidades futuras.

## Política de qualificação proposta

Distinguir: entrega aceita; ciclo autônomo observado; autonomia repetível no
escopo; recuperação operacional; distribuição reproduzível. O próximo marco
é repetibilidade, não mais uma grande reestruturação. Manter decisões de negócio
com o CEO e técnicas com Lead/CTO. Falha técnica persistente deve ter responsável,
evidência e próxima ação visíveis; nenhuma implementação pode prometer ausência
absoluta de starvation diante de recursos indisponíveis ou dependências externas.

Plano proposto para execução posterior. A auditoria não altera contratos,
recibos, cards, modelo ou configuração instalada.
