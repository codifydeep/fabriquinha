# Status do projeto — 26 de outubro de 2026

**S4 técnico qualificado; S5 encontrou um impasse de revisão e permanece não qualificado.**
O caminho usa Hermes + Kanban nativos e operações determinísticas. Multica e
Temporal não participam dessa execução. A autonomia geral, a distribuição e a
retomada do Truco continuam pendentes.

## Evidência mais recente

O [PR 59](https://github.com/codifydeep/descartavel2/pull/59) chegou a `HOMOLOGADA`
no commit `5fef1cd40cb05bcaf60db1b42b450d19ca08f473`. O operador apenas aplicou a
aprovação humana condicional do mesmo documento de negócio e observou a execução.
Depois do aceite, a equipe conduziu o ciclo inteiro sem correções, orientação
técnica externa ou reinício do controlador.

Foram conferidos nove testes, seis falhas reais no Red, três mutações cobrindo
seis alvos,
revisões independentes, CI no SHA do PR e do merge, implantação, rollback e QA
AC1/AC2. Saúde e identidade HTTP coincidiram com o commit integrado. Os dois
testes de infraestrutura anteriores ficaram intactos e a main permaneceu
inalterada. Não havia worker, claim, sandbox ou efeito pendente ao encerrar.

O runtime foi executado de uma exportação da revisão publicada, com 27 arquivos
inalterados até o final. Jobs e aceitação usaram o mesmo bundle de validação.
O [documento S4](HERMES-S4-QUALIFICATION.md) registra prova, autoria e limites.
Reutilizar um brief completo não comprova descoberta autônoma de novos requisitos.

## Consumo e operação

O ciclo usou **31 chamadas**, com **US$ 0,074938** reportados pelo provedor.
Todas têm custo e atribuição de atividade resolvidos. O contador encerrou em
**6.811/7.000**, com 189 chamadas restantes. Não houve aumento de teto ou fallback;
seguem Haiku, 40 iterações por atividade, dois workers e saída máxima 16.384.

Depois da qualificação offline dos contratos S5, o controlador foi atualizado
em manutenção drenada para a revisão publicada `2bd47470`, em outra exportação
verificada de 27 arquivos. O banco foi salvo e sua restauração conferida; código,
recibos, sessões e deploy S4 ficaram preservados. Não houve reset de board ou quota.
Produto elaborou o novo brief em uma chamada, com custo reportado de US$ 0,0019945;
o CEO aprovou Reset e Undo de um nível. A segunda versão entrou em execução pela
equipe. Esse checkpoint não é nova homologação; o contador nesse início era
6.812/7.000, com 188 chamadas restantes.

O S5 foi depois drenado por repetição de revisão: múltiplos checks AC7 e remoção
de AC8 conflitavam com o protocolo instalado. O [reparo do impasse](S5-REVIEW-IMPASSE.md)
impõe escalonamento ao CTO, mantendo revisão e gates. Passaram 330 testes e uma
prova nativa de 13 atividades/41 respostas locais, sem chamadas pagas. A manutenção
externa impede classificar todo esse ciclo como autônomo.
Na drenagem: 6.857/7.000, com 143 restantes. Das 46 chamadas desde S4, 38 têm vínculo
com S5 e oito permanecem sem atribuição, incluídas no custo reportado de US$ 0,1736602.

O escalonamento ocorreu no modelo real. O CTO manteve um `hold` técnico; a
clarificação de caminhos da base/candidatos chegou ao Lead, que encaminhou nova
orientação ao CTO. A revisão publicada `82b6dac7` corrigiu a identidade desse
encaminhamento: predecessor novo gera atendimento novo, repetição reutiliza o
mesmo. O Kanban nativo comprovou compatibilidade, reinício e status do sucessor
atual sem modelo/Docker. O controlador atualizado retomou o mesmo ciclo e criou
automaticamente outro diagnóstico CTO. O contador na instalação era 6.873/7.000.
Os três ajustes de manutenção após o aceite continuam identificados como assistência.

O lote publicado `7231004e` tornou a recusa diagnóstica explícita e indicou a
observação imutável permitida, sem afrouxar o DSL ou testes. Passaram 333 testes,
o fluxo nativo de recusa/observação/retomada e a CI de regressão com `subTest`.
Após a quarta manutenção, a equipe executou o experimento, retomou a revisão e
congelou os 18 testes de Reset, preservando os nove anteriores. O frontend
iniciou a implementação. Ainda faltam suas revisões/integração e o pacote Undo;
não houve nova homologação. O contador nesse checkpoint era 6.894/7.000.

Reset foi depois revisado e integrado no [PR 60](https://github.com/codifydeep/descartavel2/pull/60),
commit `454b845a0d4cf64f29f5a56ef3b32483b940356e`, mas o deploy foi impedido.
O seletor do primeiro pacote de uma nova release ainda cria um bootstrap em vez
de reutilizar o artefato da homologação anterior. A proteção contra substituir
um deployment diferente preservou o S4 real. O CTO comprovou 18 testes verdes
e manteve o bloqueio técnico visível. O próximo reparo deve selecionar o rollback
anterior por proveniência, sem remover containers ou afrouxar essa proteção.
O contador conferido nesse bloqueio era 6.908/7.000, com 92 chamadas restantes.

A entrega S4 foi preservada em Docker local durante a atualização. Sua execução
terminou sem cards pendentes e o polling não consome chamadas ao modelo. A outbox contém a entrega,
mas Telegram real não está configurado: fila não comprova recebimento nesse canal.

## Mecanismos qualificados

- Os [contratos S5](S5-CONTRACT-QUALIFICATION.md) acrescentam regressão conhecida
  sem duplicar testes: quatro atividades SDK, Git/Docker e CI reais, decisões
  programadas e zero chamadas pagas. Outra base ou snapshot não reutiliza a aprovação.
  A memória recupera somente a última decisão homologada; uso real por outro
  perfil continua pendente.

- O [ADR 0005](ADR-0005-VALIDATION-AND-ACCOUNTING.md) fixa scripts de validação em
  snapshots imutáveis e contabiliza custo/cache/raciocínio sem estimar ausências.
- 306 testes do núcleo e treze jobs Docker/Chromium qualificaram adição normal de
  testes e correção restrita de expectativa QA, pela entrada real da CI com Git.
- A orientação de recuperação referencia somente seu recibo. A prova nativa
  percorreu nove atividades/29 respostas locais, com reinício e parecer completo;
  comentários genuínos de PR continuam ativando a proteção contra duplicação.
- As provas locais usaram decisões programadas e zero chamadas pagas; são
  mecanismos, não julgamento autônomo. O S4 real é uma evidência separada.

Os [PRs 57](https://github.com/codifydeep/descartavel2/pull/57) e
[58](https://github.com/codifydeep/descartavel2/pull/58) permanecem homologações
assistidas. As falhas e os reparos não foram apagados nem reclassificados. No
ciclo do PR 58, 57 chamadas custaram US$ 0,147579 reportados; uma ficou sem vínculo
explícito de atividade, com custo incluído no total. Ausência não foi tratada como
zero nem atribuída por horário/prosa.

## Próximas fronteiras

| Marco | Evidência | Pendência |
|---|---|---|
| S0/S1 | Integração Hermes/Kanban; upstream sem patches | Não constitui entrega de produto |
| S2/S3 | TDD, revisão, operações e recuperação delimitada em isolamento | Não equivale a julgamento real universal |
| P1/P3 | Reparo até homologação assistida dos PRs 57/58 | História preservada; não é autonomia |
| P2 | Bundle e custos reais conferidos até homologação | Atribuição completa de chamadas auxiliares não é garantida |
| P4/S4 | PR 59: ciclo técnico completo sem intervenção externa | Escopo Python/HTTP e brief já aprovado |
| P5/S5 | Ainda não qualificado | Segunda versão, dois pacotes dependentes, regressão e memória entre perfis |
| P6/S6 | Preparação parcial | Instalação reproduzível em outro repo, canais e corte do legado |
| P7/S7 | Não iniciado | Retomar Truco após qualificação |

O [plano S5](S5-CONTINUITY-PLAN.md) orienta o próximo trabalho. Não repetir outro
ensaio genérico de saudação. Os contratos de regressão e projeção histórica
passaram offline; a próxima fronteira é uma segunda versão na mesma aplicação.
O novo brief foi aprovado; o mesmo ciclo continua após instalar os reparos
de escalonamento e identidade. Não iniciar outra release ou resetar o board para esconder o
impasse. Continuidade, recuperação real e nova homologação só serão declaradas
após a conferência das evidências, identificando a assistência técnica externa.

O [roadmap](ROADMAP.md) mantém o objetivo completo. As revisões de
[24/10](SIMPLIFICATION-REVIEW-2026-10-24.md),
[25/10](EXECUTION-REVIEW-2026-10-25.md) e
[26/10](EXECUTION-REVIEW-2026-10-26.md) preservam sua análise histórica.
Não há promessa de recuperação universal ou ausência universal de starvation.
