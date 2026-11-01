# Recuperação delimitada da autoria de testes sem submissão

Manutenção de plataforma autorizada pelo operador, não uma nova ferramenta para
os agentes reiniciarem suas próprias tarefas. O ciclo recebe `assisted=true`.
Não equivale a reparar testes congelados nem aprova a entrega.

`authoring_recovery.admit` exige instalação pausada e drenada, fonte verificada,
release ativa, grafo exato e diagnóstico CTO concluído ligado à última tentativa.
A causa deve ser encerramento sem handoff, na autoria de testes, com workspace
**idêntico à base**. Qualquer Red, revisão ou freeze já registrado exige outro
caminho. Efeitos pendentes, tentativa de revisão, implementação, contrato alterado,
trabalho parcial e execução de sucessores impedem esta operação.

A autorização operacional é atual; o hold antigo do CTO permanece histórico e
não é reinterpretado como aprovação. O pacote concluído fica intacto. Criam-se
apenas os cards sucessores da parte pendente, com os mesmos responsáveis, critérios,
dependências, plano aprovado e validador. As novas áreas começam vazias; o fluxo
normal restaura a base e exige Red, revisão independente, freeze, Green, controles
negativos, PR, CI e QA. A fonte recebe contexto explícito da recuperação.

Os cards novos nascem bloqueados. A transação dos cards é confirmada antes de
publicar o recibo e o ponteiro do grafo. Uma interrupção entre esses passos retoma
a transição registrada. A identidade idempotente impede duplicação. O dispatcher
normal só libera os cards depois de a instalação ser retomada. A origem continua
em triage; histórico e snapshots não são apagados.

Há uma única recuperação deste tipo por release. Não há reset de tentativas nem
repetição por mudança de data/modelo. Novo fracasso permanece sujeito ao diagnóstico
técnico e aos limites existentes. Esta operação não comprova autonomia do ciclo.

Validação: casos negativos de fase, identidade, erro funcional, efeito pendente,
workspace e contrato alterados; ensaio nativo em cópia isolada com interrupção
entre publicação do recibo e do grafo, retomada idempotente e seis sucessores
únicos. Prefixo concluído, fonte em triage, plano, validador e contagem de runs
preservados. Nenhum worker, chamada ao modelo ou operação Docker nesse ensaio.

Instalação realizada após backup conferido e pausa drenada. O dispatcher retomou
a autoria em card sucessor; seis cards pendentes foram encadeados e o primeiro
pacote concluído permaneceu intacto. Suite do núcleo: 560 testes aprovados.
Execução iniciada não significa Red aceito, entrega concluída ou homologação.
