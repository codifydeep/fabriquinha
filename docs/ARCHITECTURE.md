# Mapa da implementação

Este documento descreve o código instalado, não uma arquitetura futura com Temporal.

| Área | Entradas principais |
|---|---|
| Configuração e contratos | `team.example.json`, `kit_contract.py`, `project_selection.py`, `portable_contract.py`, `portable_run_spec.py` |
| Brief e planejamento | `planning_intake.py`, `planning_schema.py`, `planning_contract_review.py`, `materialize_plan.py`, `compile_planned_sequence.py` |
| Coordenação persistente | `brief_delivery_supervisor.py`, `dependent_sequence.py`, `sequence_supervisor.py`, `portable_supervisor.py` |
| Multica e ACP | `acp_wrapper.py`, `broker/native.py`, `broker/acp_transport.py`, `broker/acp_probe.py` |
| Broker e handoffs | `broker/server.py`, `broker/handoffs.py`, `broker/handoff_runtime.py` |
| TDD e entrega congelada | `broker/tdd_evidence.py`, `broker/test_first_protocol.py`, `review_instruction.py`, `additive_test_policy.py` |
| Modelo e limites | `model_policy.py`, `model_proxy.py`, `broker/worker_model_config.py` |
| CI, publicação e QA | `portable_delivery.py`, `publication_access.py`, `portable_qualification.py`, `portable_browser_qa.py`, `browser_feedback_acceptance.py`, `deploy/` |
| Memória e contexto | `generated_context.py`, `broker/session_resume.py`, módulos de recuperação contextual no broker |
| Supervisão host | `register_brief_delivery_service.py`, `register_portable_host_service.py`, `host_awake_guard.py` |
| Docker e limpeza segura | `docker_grouping.py`, `cleanup_delivery_test_containers.py`, `cleanup_obsolete_images.py` |

Os caminhos acima são relativos a `team-delivery-kit/`. Não são APIs estáveis ainda.

## Fontes de verdade e responsabilidade

Multica apresenta issues, atribuições e sessões. Os controladores mantêm ledgers e recibos; GitHub mantém commits, PRs e checks. Snapshots preservam a entrega que o revisor examinou. Texto de um agente não substitui nenhum desses registros.

Sessões são contexto de conversa, não a única memória de um projeto. Decisões, critérios, evidências e incidentes devem ser recuperáveis por identidade durável. Contexto ou memória não concedem novas permissões. A recuperação entre perfis e projetos continua sendo uma dimensão de qualificação, não uma garantia universal.

### Contexto integral sem truncamento

`execution_context.py` permite registrar conjuntamente o contexto de implementação e as instruções de revisão, com hash SHA-256 e limite explícito de 12.000 caracteres por conteúdo. A issue pode transportar apenas uma referência. O broker resolve a referência a partir da rota imutável do controlador, verifica issue, perfil e modo e registra um recibo por execução antes de apresentar o conteúdo integral ao agente. Não há leitura de URLs arbitrárias nem concessão de ferramentas por essa referência. Uma alteração de conteúdo invalida o hash; uma referência não registrada é rejeitada.

A compilação usa esse mecanismo somente quando habilitado explicitamente. As rotas legadas mantêm seus limites anteriores. Sua validação offline não equivale à qualificação de uma entrega autônoma; a instalação e o ensaio ponta a ponta continuam necessários.

### Revisão de testes e recuperação sem permissões implícitas

`broker/test_revision_review.py` separa a aprovação dos testes da aprovação da entrega. Uma revisão aprovada permite implementar contra o Red congelado; não permite alterar testes, integrar código ou declarar homologação. O revisor lê snapshots completos e não dispõe de terminal ou escrita.

`typed_decision_contract.py` permite uma única correção de comprimento por execução, registrada no ledger do proxy. Somente os campos textuais excedidos podem mudar. Parecer, achados, identificadores e referências não podem ser trocados ou removidos. A resposta original permanece rejeitada; o proxy não executa ferramentas nem aceita o parecer em nome do controlador.

`broker/review_format_recovery.py` qualifica uma nova revisão somente leitura após uma mudança comprovada do contrato. Preserva a rejeição anterior, as leituras e o snapshot; não reinicia o autor nem repõe tentativas de bootstrap. A imagem instalada é verificada por um teste fixo sem chamadas ao provedor.

`broker/technical_replan_certificate.py` certifica uma decisão efetivamente tomada pelo CTO após inspeção integral do candidato que falhou na suíte congelada. O certificado liga issue, execução, falha, Red e leituras. `portable_test_revision_recovery.py` continua impondo profundidade limitada: uma revisão adicional exige esse certificado, novo Red e revisão independente. Não há autorização para editar a baseline ou concluir a release. Falhas além do limite permanecem visíveis para um novo diagnóstico, não viram retries idênticos.

`pre_red_supervision.py` reconcilia projeções antigas com esses registros e tarefas nativas atuais, mesmo quando uma revisão termina entre duas observações. Essa retomada é de acompanhamento: não cria um parecer, um worker ou uma permissão.

## Limites reais de portabilidade

Há contratos genéricos, mas também scripts com nomes de cards, repositórios, caminhos locais, SHAs e imagens de ensaios. `projects/` preserva esses exemplos para testes e rastreabilidade; não deve ser ativado automaticamente em instalações novas. Overrides `port2` e LaunchAgents históricos exigem revisão antes de uso em outra máquina.

O código histórico em `bootstrap/infra/` não deve ser ligado simultaneamente ao kit. Configurações pessoais dessa instalação, vendors, worktrees e estados não fazem parte da exportação pública.

## Observabilidade e evolução de papéis

Todo recurso deve avaliar se instrumentação é necessária, desnecessária ou adiada. A infraestrutura de análise de produto/A-B ainda não está instalada. O contrato de evolução está em [`contracts/observability.md`](../team-delivery-kit/contracts/observability.md). DevOps consome métricas operacionais; Produto consome dados agregados; observabilidade não concede autoridade para coletar dados pessoais.
