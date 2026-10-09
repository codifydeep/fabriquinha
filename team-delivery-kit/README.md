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
