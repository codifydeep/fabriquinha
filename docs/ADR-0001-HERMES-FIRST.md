# ADR 0001 — Coordenação única e entrega mínima

Data: 24/10/2026. Estado: aprovado pelo proprietário para S0/S1.
Plano: [revisão estratégica](SIMPLIFICATION-REVIEW-2026-10-24.md).

## Decisão

Validar Hermes + Kanban como único ciclo de vida de trabalho antes de migrar a
instalação atual. A prova usa um namespace independente, workers determinísticos
isolados e nenhuma chamada ao modelo. Multica e os dados anteriores ficam como
referência pausada. Não retomar a construção de adaptadores v2 como pré-requisito.

Foram aprovadas as mudanças de contrato propostas:

- Revisão de diff, testes e contexto afetado, expansível, substitui a obrigação
  universal de ler todo o repositório página por página.
- Implementação poderá editar, aplicar patches e executar testes na sandbox;
  testes congelados, políticas e credenciais continuam protegidos.
- Uma política comum de incidentes substitui recuperações por caso histórico.
- Identidade autenticada na borda e recibos de artefatos substituem a repetição
  de toda a linhagem de sessão em cada camada.

TDD, revisão independente, imutabilidade, proteção de regressões, PR/CI e QA sobre
o commit/artefato implantado continuam obrigatórios. Mudanças de estado do board
não constituem autorização de merge ou homologação.

## Escopo e condição de escolha

Single-host, um projeto ativo, no máximo dois workers e um por perfil. A opção
Hermes depende da demonstração S1 com uma integração pequena, sem scheduler
paralelo, alteração do loop de inferência ou importação do broker histórico.
Se a fronteira não couber nesse desenho, avaliar Multica enxuto como alternativa.

A referência Git anterior é `ad68e656`; o recibo privado S0 confere o backup
existente por hashes, restauração SQLite e integridade. Não há reset dos ensaios
antigos, de aprovação ou do medidor do modelo. A pausa financeira permanece.

## Inventário de responsabilidades

| Classificação | Componentes |
|---|---|
| Referência instalada, sem novo despacho | Multica, runtime/broker port2 e seus bancos/recibos |
| Preservado parado | Proxy de modelo, scheduler host, antigos gateways Hermes/Truco |
| Candidatos a aproveitamento | Agrupamento Docker, limpeza scoped, proteção de publicação, políticas de qualidade e operações de QA |
| Novo ensaio isolado | Hermes upstream fixado, Kanban nativo e adaptador determinístico S1 |
| Fora da S0/S1 | Migração, produto Truco, execução com modelo, publicação de produto e implantação de release |

Os contratos antigos continuam descrevendo seus ensaios históricos. A política
aprovada rege a nova linhagem após sua qualificação; não alterar recibos antigos
para fazê-los satisfazer o novo desenho.
