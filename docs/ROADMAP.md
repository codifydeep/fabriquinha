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
