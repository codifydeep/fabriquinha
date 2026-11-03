# Estado de qualificação

Referência: 3 de novembro de 2026. Plataforma experimental Hermes + Kanban.
Este documento descreve limites públicos, não o estado vivo de uma instalação.

## Evidências existentes

- Entregas web Python/HTTP locais com TDD, revisão independente, PR/CI,
  implantação, rollback e QA, nos cenários delimitados dos relatórios S4/S5.
- Dois incrementos dependentes em um ciclo observado sem intervenção após
  o aceite (v0.3, conforme o balanço histórico de 30/10).
- Recuperações determinísticas e algumas recuperações reais pelos agentes.
- Leitura paginada de relatórios diagnósticos preservados pelo controlador;
  suíte offline de 579 testes passou antes da limpeza da distribuição.

## Ainda não comprovado de forma geral

- Entregar qualquer brief sem intervenção operacional.
- Recuperar todo impasse de ferramentas, testes, revisão ou infraestrutura.
- Instalação completa reproduzível por terceiros em outro ambiente.
- Suporte geral a outras stacks, mobile ou múltiplas releases concorrentes.

Experimentos offline assistidos não são homologações. O ciclo corrente de reparos
continua assistido até passar pelos gates nativos. Consulte o Kanban da própria
instalação para execução, responsável e impedimentos atuais.

[Roadmap](ROADMAP.md) · [Relatórios e contratos](README.md)
