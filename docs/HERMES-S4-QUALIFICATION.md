# S4 — Primeiro ciclo técnico completo sem intervenção externa

Qualificado em 26/10/2026, no [PR 59](https://github.com/codifydeep/descartavel2/pull/59),
commit `5fef1cd40cb05bcaf60db1b42b450d19ca08f473`.

## Escopo e resultado

Uma instalação com perfis, board e sessões novos recebeu o documento de negócio
já aprovado pelo proprietário. Produto submeteu uma nova proposta idêntica; a
aprovação condicional anterior foi aplicada somente depois de conferir seu hash.
Não foram importados planos, testes ou aprovações técnicas antigos.

Depois desse aceite, a equipe conduziu planejamento, TDD, revisões, PR, CI local,
merge, implantação, rollback/restauração e QA. O controlador emitiu `HOMOLOGADA`.
O operador observou e auditou após a entrega; não editou artefatos, transições ou
código do runtime, não orientou tecnicamente os agentes e não reiniciou o serviço.

Esta é uma prova de entrega técnica autônoma para a stack Python/HTTP local,
Linux ARM64 em Docker na máquina de referência. Reutilizar um brief completo não
comprova descoberta autônoma de requisitos novos. O ensaio não qualifica todas
as stacks, recuperação universal ou instalação reproduzível por terceiros.

## Evidências conferidas

| Fronteira | Resultado |
|---|---|
| Execução | Revisão publicada `8ca85299330f4f7b083d382ee2d4e50a67a20268`, exportada antes do início; 27 arquivos permaneceram intactos |
| Brief | Documento de negócio idêntico ao autorizado; novo recibo nativo, sem dispensar gates técnicos |
| Plano | Tech Lead propôs; CTO revisou independentemente |
| Red | QA produziu testes; seis falhas comportamentais reais; baseline anterior passou |
| Freeze | Tech Lead revisou os testes; entrega imutável e testes anteriores preservados |
| Implementação | Tech Lead obteve Green; nove testes completos e três jobs de mutação cobrindo seis alvos |
| Revisão da entrega | CTO aprovou o snapshot exato, com reexecução independente; nenhum autor revisou a própria entrega |
| GitHub | PR e merge pela equipe; CI local verde no SHA do PR e no commit integrado |
| Deploy/QA | Compose local, health/identity, rollback/restauração e QA independente AC1/AC2 no mesmo commit |
| Aceitação | `HOMOLOGADA` emitida automaticamente com commit, URL, imagem e provas |
| Quiescência | Nenhum worker, claim, sandbox ou efeito pendente ao encerrar; nenhum incidente ou intervenção técnica externa |

A inspeção dos testes confirmou execução HTTP/Chromium: nome normalizado sem
navegação, HTML literal sem injeção de elementos, entrada vazia e só com espaços,
e recuperação de erro por submissão válida. Os dois testes anteriores de
infraestrutura permaneceram intactos. Os testes auxiliares que não falharam no
Red continuaram na suíte completa; os controles seguem o contrato F1 aprovado.

A auditoria também conferiu autoria e revisão nos runs nativos, ausência de
comentários/eventos administrativos, hashes da exportação, CI atual no GitHub,
identidade HTTP do ambiente e branch de produto. A main permaneceu inalterada.
Recibos, sessões e detalhes de instalação ficam privados; não são distribuídos.
A independência é lógica entre perfis/processos, usando a mesma conta GitHub e
o mesmo modelo; não se afirma diversidade de contas ou de modelos revisores.

## Consumo observado

Foram 31 chamadas ao modelo configurado, todas com custo reportado e vínculo de
atividade resolvido: **US$ 0,074938**. O valor veio da resposta do provedor e não
é estimativa de preço, teto monetário ou fatura. Tokens/cache/raciocínio continuam
com contadores próprios, sem dupla contagem. Nenhum fallback foi configurado.

O limite permaneceu em 40 iterações por atividade, dois workers e saída máxima
de 16.384 tokens. As esperas de integração foram agendadas no Kanban, sem prender
um worker ou consumir chamadas de modelo por polling.

## O que esta prova não encerra

- Os PRs 57 e 58 continuam classificados como recuperações assistidas.
- Falta uma segunda versão na mesma aplicação com dois pacotes dependentes,
  regressão e memória efetivamente usadas entre perfis.
- Falta qualificar o conserto de uma base cujo teste existente já falha, sem
  enfraquecer os testes ou aceitar a cabeça vermelha.
- Falta instalação/upgrade/rollback reproduzíveis em outro repositório e corte
  do legado. A preparação deste S4 ainda teve operações explícitas do operador.
- A outbox gerou a entrega; o transporte Telegram real não está configurado.
  Enfileirar não comprova que o CEO recebeu uma mensagem nesse canal.
- O Truco ainda não foi retomado. Autonomia geral da plataforma não está concluída.

O [roadmap](ROADMAP.md) mantém S5/S6/S7 abertos. Não repetir um S4 genérico para
melhorar uma métrica: a próxima fronteira é continuidade, com nova aprovação do
brief quando o conteúdo de negócio mudar.
