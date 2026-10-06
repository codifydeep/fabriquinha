# Critérios para declarar autonomia

Não usamos quantidade de código, workers ativos ou percentual subjetivo como comprovação.

## Entrega

- Novo brief: refinamento, aprovação de negócio, arquitetura e decomposição pelos agentes.
- Cards dependentes: TDD, revisão independente, correção do autor e integração por PR.
- QA funcional e de regressão no commit implantado, com URL e recibos duráveis.
- Ciclo completo sem o operador editar artefatos, guiar handoffs ou dispensar controles.

## Resiliência

- Falha de worker, controlador e reinício do host sem duplicar entregas.
- Indisponibilidade do modelo, Telegram/interface ou GitHub visível e recuperável.
- Impedimento técnico escalado para Tech Lead/CTO; CEO somente para decisões de negócio, autoridade ou credenciais indispensáveis.
- Sem starvation silenciosa, looping de ação idêntica ou conclusão fictícia.
- Memória útil entre perfis e rodadas, preservando isolamento e proveniência.

## Reutilização

- Instalador único, configuração declarativa e remoção de dependências da máquina original.
- Imagens reproduzíveis e publicáveis, matriz de plataformas e política de atualizações.
- Novo repositório e nova instalação limpa sem copiar credenciais, sessões ou fixture identities.
- Licença escolhida pelo proprietário, documentação de operação e testes de atualização/rollback.

Esses gates permanecem abertos até evidência específica. O ensaio atual não retoma automaticamente o Truco.
