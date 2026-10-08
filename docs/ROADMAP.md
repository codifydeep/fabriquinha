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

## Compatibilidade de transporte dos modelos

O adaptador de Haiku preserva o contrato canônico validado localmente. Para
revisões tipadas, apenas o schema enviado ao provedor omite os combinadores
`anyOf` que o endpoint rejeita. SHA, campos obrigatórios, ferramentas permitidas
e limites permanecem vinculados; citações observadas e consistência entre
parecer e findings continuam obrigatórias no validador local. Uma resposta
inválida não constitui aprovação, mesmo que o provedor aceite o pedido.

`model_review_smoke.py` exercita esse transporte com uma fixture explicitamente
sintética, sem acesso a artefatos reais ou concessão de autoridade. Seu sucesso
não recupera automaticamente uma revisão bloqueada e não qualifica entrega.

Uma recuperação de revisão pode ser autorizada pelo controlador somente após
conferir a qualificação sintética no ledger e nos logs do proxy instalado, a
identidade do revisor, a lease encerrada, a leitura integral e o mesmo snapshot.
O histórico da falha fica preservado e o novo handoff tem identidade distinta.
Essa recuperação é única: outro erro não reinicia o contador nem libera o autor.
Seu parecer ainda precisa passar pelos controles normais e não homologa a release.

Conclusão de task e fechamento de lease são observações distintas. A validação
aguarda a finalização da mesma lease, com identidade e prazo persistentes, antes
de congelar arquivos. Um atraso de fechamento não é falha funcional, não autoriza
correção pelo autor e não constitui entrega. Incidentes históricos dessa corrida
só retornam à validação se a lease estiver fechada, não houver diagnósticos ativos
e nenhuma falha funcional tiver sido produzida; o histórico permanece preservado.
