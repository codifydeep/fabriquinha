# Próximos marcos

A sequência detalhada proposta, os critérios de saída e o balanço crítico estão
em [Estratégia de recuperação](DELIVERY-RECOVERY-STRATEGY.md). O plano distingue
correção offline, entrega assistida e comprovação posterior de autonomia.

1. **Concluir a recuperação atual pelo fluxo nativo.** Diagnóstico com relatório
   acessível, decisão válida, retorno ao autor e revisão independente. Preservar
   resultados assistidos; não reinterpretar experiências offline como aprovações.
2. **Concluir a entrega.** Congelamento adequado, suíte completa e controles
   negativos, PR, CI no SHA exato, implantação e QA com recibo final verificável.
3. **Comprovar autonomia repetível.** Uma entrega útil com dois incrementos
   dependentes após o aceite, sem alterações manuais em cards, testes ou workspaces.
   Eventuais impedimentos devem ser resolvidos pelo fluxo registrado.
4. **Qualificar distribuição.** Clone limpo, dependências fixadas, preparo privado
   documentado, backup/restauração e entrega em uma segunda instalação. A limpeza
   do repositório melhora a entrada, mas não substitui essa prova.
5. **Expandir somente após essas evidências.** Novas stacks, mobile, observabilidade
   de produto e experimentação devem ter contrato e validação próprios.

Manter Hermes + Kanban, controles de regressão e revisão independente. Não
introduzir orquestradores ou serviços para contornar lacunas de protocolo.

## Mudanças aprovadas para a primeira entrega após a homologação atual

Aplicar as três mudanças abaixo entre os marcos 2 e 3. A condição de início é a
release atual chegar a `HOMOLOGADA`, com recibo que vincule PR, CI, commit
implantado, URL e QA. Até lá, a equipe segue o contrato da rodada em andamento.

1. **Um responsável por incremento até a homologação.** Produto conduz o brief
   e o Tech Lead identifica no Kanban quem responde pela entrega de cada
   incremento. Essa pessoa acompanha dependências, pede ajuda a especialistas e
   retoma a atividade depois de cada consulta. O revisor independente conserva
   autoridade para solicitar mudanças. Um reinício deve recuperar o responsável
   e a próxima ação pelo card.
2. **Experimentação local rápida com critérios de entrega rigorosos.** Dar ao
   responsável uma operação simples para reproduzir uma hipótese em cópia
   descartável e executar primeiro o cenário relevante. Registrar o resultado
   como diagnóstico. Para integrar e homologar, exigir TDD, proteção das
   regressões, congelamento e revisão independentes, suíte e controles completos,
   PR, CI no SHA testado e QA no commit implantado.
3. **Comparar os dois desenhos na próxima entrega útil.** Antes de iniciar os
   novos incrementos, extrair a linha de base da rodada encerrada pelos eventos
   do Kanban, recibos de validação e registros de consumo. Medir do aceite do
   brief à URL validada, com custo, intervenções humanas após o aceite e
   regressões detectadas. Separar tempo de execução, espera pelo controlador e
   retrabalho; identificar dados ausentes e distinguir regressões reais das
   falhas introduzidas nos controles negativos. Manter Hermes + Kanban, modelo e
   critérios de qualidade para a comparação. Registrar diferenças de escopo e
   complexidade entre as entregas ao interpretar o resultado.
