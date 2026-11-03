# Utilitários de compatibilidade

Este diretório conserva somente o agrupamento Docker e a limpeza delimitada
exigidos pelo núcleo e por AGENTS.md, com seus testes. O caminho é preservado
porque faz parte dos imports e exportações verificadas da instalação atual.

- `docker_grouping.py`: labels Compose para recursos descartáveis.
- `cleanup_port2_history.py`: preview de helpers históricos port2 com escopo fixo;
  não é uma limpeza genérica de projetos.
- `cleanup_obsolete_images.py`: preview e aplicação por hash de plano, com
  proteção de imagens em uso, fontes, aliases, rollback e outros projetos.

Não há controlador Multica ou instalador aqui. O legado anterior está no histórico
Git. Arquivos ignorados presentes em uma instalação antiga não fazem parte da
distribuição. Não use prune global e não remova volumes ou dados de recuperação.
