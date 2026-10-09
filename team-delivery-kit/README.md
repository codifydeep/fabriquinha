# Team Delivery Kit

Implementação ativa da [Fabriquinha](../README.md): Multica, workers Hermes,
broker de execução e controladores persistentes de entrega.

## Entradas

- [Arquitetura e mapa dos módulos](../docs/ARCHITECTURE.md)
- [Instalação segura](../docs/SETUP.md)
- [Estado das validações](../docs/VALIDATION.md)
- [Gates restantes para autonomia](../docs/ROADMAP.md)
- [Catálogo de papéis](team.example.json)
- [Contrato de observabilidade](contracts/observability.md)

## Testes offline

Com o ambiente Python criado conforme o README da raiz:

```bash
PYTHONPATH=. python -m unittest discover -s tests -q
```

Os testes usam fixtures públicas e simulações; não disparam agentes reais.
O canário HTTP de recuperação abre um servidor temporário em loopback.

## Plano de controle

```bash
python evalctl.py init
python evalctl.py up
python evalctl.py verify
python evalctl.py status
python evalctl.py stop
```

Isso não instala automaticamente o broker, a equipe nem um fluxo completo.
`status` também verifica serviços opcionais e pode retornar não-zero quando
eles ainda não foram instalados; não é uma declaração de autonomia.

### Diagnóstico de decisões rejeitadas

O proxy mantém recibos correlacionados por execução e hash da resposta. Uma
decisão tipada inválida registra as restrições JSON Schema violadas, incluindo
restrições internas de `anyOf`, sem publicar valores, caminhos de instância ou
mensagens do validador. O diagnóstico é persistido junto ao recibo de rejeição;
não executa ferramentas, não corrige argumentos e não aprova entregas.
Recibos antigos sem essa informação permanecem incompletos: não se deve inferir
a restrição ausente nem convertê-los retroativamente em evidência de recuperação.

`test_diagnosis_recovery_cli.py` admite uma única nova decisão read-only do CTO
após rejeição tipada comprovada. É uma operação administrativa, sem endpoint
para workers, e exige manutenção selada, execução terminal, correlação nativa,
recibo persistido no proxy e leituras completas dos snapshots atuais. Preserva
o diagnóstico anterior e a revisão independente; não reinicia o autor nem
converte a tentativa em aprovação. O reconciliador normal valida a nova decisão.
Nova falha permanece bloqueada, sem repetição idêntica. Esse caminho não prova
recuperação autônoma: sua admissão inicial ainda requer o operador.

Replanejamentos após rejeição de testes usam o certificado
`immutable-test-review-replan-v1`, distinto do certificado de falha de Green.
Ele vincula a decisão real do CTO ao snapshot, à revisão independente e às
leituras completas de candidato/anterior. O supervisor reobserva a decisão e
seus achados antes de retomar a correção; não transforma o parecer em aprovação.
O limite atual continua sendo uma revisão adicional no segundo nível. Falhas
além desse limite exigem outra estratégia de diagnóstico, ainda não uma
retentativa idêntica ilimitada.

Os supervisores de brief e de entrega adiam seu início enquanto o controlador
está em manutenção. Essa consulta é um preflight conservador, não uma reserva
distribuída de despacho: uma manutenção iniciada após a consulta ainda precisa
ser cercada pelo broker. Uma recusa nessa janela não é falha funcional do autor.

## Convenções

`broker/` concentra isolamento, autorização, handoffs e recuperação.
`deploy/` contém caminhos de implantação. `projects/` contém configurações
de ensaio e fixtures: nomes, IDs, hashes, caminhos e imagens devem ser
substituídos e validados em uma instalação nova, nunca ativados por wildcard.

Dockerfiles numerados, overrides `port2` e scripts de recuperação específica
preservam código da evolução dos ensaios; não são um instalador universal.
Imagens locais antigas podem não existir em outra máquina. Leia as limitações
antes de chamar scripts que criam issues, alteram GitHub ou usam modelos pagos.

Os relatórios e diários operacionais da instalação original ficam privados.
`evaluation/` exporta apenas o lock de proveniência, um fixture de isolamento
sem modelo necessário aos testes e código de experimentos históricos.
