# ADR 0006 — Aceitação compartilhada e autoridade técnica

Estado: **aceito pelo proprietário em 27/10/2026**, ao aprovar F2/F3 e o plano
da [auditoria pré-S6](EXECUTION-REVIEW-2026-10-27.md). Implementação qualificada
offline e instalada no S6; o despacho foi retomado após preparação operacional.

## F2 — Uma suíte para prévia e homologação

O contrato versão 2 usa unittest/Playwright. O controlador executa a mesma suíte
congelada no Red/Green/controles/CI e contra o endereço implantado. O comando e
o endereço pertencem ao controlador; agentes escrevem testes do produto.

- `acceptance_*.py`: classes que herdam diretamente de `AcceptanceTest`, com
  métodos `test_*`. `self.target` identifica o aplicativo; `self.new_context()`
  cria uma sessão isolada e registra limpeza. Asserções e temporizadores usam
  unittest/Playwright/Python, sem uma linguagem própria de interação.
- `acceptance.*.json`: cobertura dos critérios por IDs de testes reais e,
  quando semanticamente adequado, gates `full_suite`/`regression`. O manifesto
  não implementa cenários nem aprova sua própria cobertura.
- O inventário estático deve corresponder à descoberta e execução completas,
  inclusive no Red. Falha unitária não pode mascarar aceitação que não iniciou.
  Seleção parcial, skips, testes inventados e cobertura duplicada são recusados.
- O revisor independente avalia a suficiência semântica. Critérios de qualidade
  não precisam virar texto fictício na UI. Os gates declarados só contam após
  conferir suíte integrada, freeze, snapshot e proteção dos testes.
- Cada incremento acrescenta arquivos. Testes e manifestos anteriores continuam
  protegidos. SHA/saúde do deploy são conferidos fora dos testes autorais.
- Um critério transversal pode receber casos adicionais no manifesto do próximo
  incremento. A cobertura é a união aditiva dos arquivos imutáveis. Repetir
  cobertura idêntica ou duplicar o mesmo caso no mesmo critério é recusado;
  nenhuma extensão substitui os casos/gates anteriores.
- Preview usa container sem rede externa, credenciais ou socket; QA alcança o
  aplicativo em rede interna própria. Snapshots ficam somente para leitura.
- A stack permanece Python/HTTP local. Contextos isolam cookies/storage; fixtures
  precisam tratar estado compartilhado do servidor. WebSockets e dependências
  externas não foram habilitados.

O seletor pertence à instalação, não ao conteúdo do agente. Recibos identificam
versão e bundle. O modo novo recusa arquivos QA legados para impedir omissão
silenciosa. Instalações/provas antigas conservam seus validadores; não são
convertidas retroativamente.

## F3 — Autoridade de qualidade

O brief governa o negócio; este contrato governa correções técnicas e substitui
a redação anterior que exigia CEO para toda correção de teste. O aceite de
escopo S6 fica preservado, sem editar silenciosamente seu documento.

Autor corrige candidatos antes do freeze; revisor nunca edita a entrega. Revisão
técnica de teste congelado exige nova versão justificada, revisão independente
e todos os gates. Lead/CTO tratam questões técnicas. Mudança de negócio ou remoção
de cobertura exige aprovação específica do CEO.

A implementação inicial mantém o reparo de produto e **não habilita correção
arbitrária de testes Python congelados**. A exceção JSON-text do ADR 0004 vale
nas instalações daquele contrato. Uma operação sem suporte no modo 2 fica como
impedimento técnico explícito ao CTO, sem retries iguais ou depuração pelo CEO.

## Instalação e qualificação

`configure-acceptance --expect-validation <hash-atual>` usa a entrada pública
do operador. Exige pausa, workers/efeitos drenados, provedor desabilitado e board
ainda sem planejamento ou entrega para a instalação inicial. Um reparo do modo 2
já instalado pode preservar planejamento aprovado, desde que não exista nenhum
job de validação, baseline/Red/freeze ou outro recibo de qualidade/diagnóstico.
Uma atividade interrompida sem tais evidências não é uma entrega validada.
Preserva o vínculo anterior em recibo e versiona também o bundle fixado no grafo
aprovado, sem editar cards ou dependências. A gravação do grafo precede a da
instalação. Uma interrupção mantém o despacho bloqueado por divergência; repetir
o comando com o hash anterior completa a mesma transição, sem duplicar recibos.
A recuperação também reconhece instalações antigas com a ordem inversa de
gravação. Não inicia despacho nem muda o projeto/brief.

Os testes do núcleo cobrem instalação tardia, bundle divergente, recibos antigos,
inventário parcial e preservação da configuração anterior.
`scripts/qualify_acceptance_suite.py` usa Docker/Chromium reais para verificar
sessões independentes, recusa do terceiro participante, prazo de três segundos,
controle atrasado, filesystem somente leitura, ausência de credenciais/socket/
acesso externo e recusa de skip/seleção parcial. A mesma suíte passa na prévia
e no alvo implantado; o atraso é recusado nos dois.

O lifecycle é validado separadamente com
`scripts/qualify_hermes_release.py --acceptance-suite`, Hermes nativo e transporte
GitHub/autores/revisores programados. Uma primeira execução identificou Red
parcial após falha de identidade do bootstrap; o caso foi preservado e ganhou
teste de regressão. Qualificação offline não representa autonomia de modelo
real, entrega S6 ou dispensa de PR/CI/revisão.

Resultado de 27/10: 396 testes do núcleo passaram. A prova isolada de navegador
passou em sete jobs reais. A prova corrigida do lifecycle completou dois
incrementos dependentes, 11 atividades SDK e 19 requisições ao transporte local
programado. Preservou testes anteriores e conferiu os critérios GREET, BYE e
REGRESSION com o mesmo contrato na prévia e no deploy. Nenhum patch upstream,
chamada paga ou mutação GitHub real; os deployments descartáveis foram retirados
depois de salvar evidências. As duas primeiras provas falhas permanecem arquivadas.

O reparo aditivo seguinte passou com 401 testes do núcleo e outra execução da
mesma cadeia de dois incrementos. O critério NAMED recebeu casos dos dois pacotes
sem alterar o primeiro manifesto; prévia, controles, integração e QA preservaram
os casos anteriores. A instalação S6 foi atualizada antes de qualquer job ou
recibo de qualidade, conservando seu plano aprovado e sua intervenção registrada.
