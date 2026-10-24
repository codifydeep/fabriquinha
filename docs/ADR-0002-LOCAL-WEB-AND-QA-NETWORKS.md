# ADR 0002 — Acesso local ao web e isolamento da rede de QA

Data: 24/10/2026. Escopo: stack inicial Python/HTTP na qualificação S3.
Estado: decisão técnica aplicada na candidata isolada; não é migração do runtime.

## Evidência

O primeiro Compose deixou o servidor saudável em uma rede `internal`, mas não
publicou porta no host. `NetworkSettings.Ports` continha uma lista vazia, embora
a configuração solicitasse publicação em `127.0.0.1`. O efeito atingiu seu prazo
persistente sem ser repetido. A tentativa foi preservada como falha, não entrega.

Dois probes descartáveis confirmaram que omitir a porta do host publica uma
porta dinâmica na bridge, mas não na rede interna dessa instalação. A
[documentação de redes Compose](https://docs.docker.com/compose/how-tos/networking/)
distingue redes internas de redes com conectividade externa. A
[referência de serviços](https://docs.docker.com/reference/compose-file/services/)
documenta o endereço de bind e a publicação de portas.

## Decisão

- Serviço `web` em duas redes do próprio projeto: bridge `default` e `qa` interna.
- Porta publicada somente em `127.0.0.1`, com número dinâmico resolvido do Docker.
  A configuração omite `published`; não usa uma porta fixa nem bind em todas as interfaces.
- Job de navegador ligado somente à rede interna `qa`. Driver confiável permite
  apenas requisições ao `web` e nega WebSockets na stack HTTP inicial.
- Workers de código e jobs de suíte mantêm sua fronteira própria; esta decisão
  não lhes concede rede externa, socket Docker, credenciais ou banco do Kanban.
- QA confere a URL de loopback no host, a identidade HTTP e a imagem real, antes
  e depois do cenário de navegador. Servidor saudável sem URL acessível não basta.
- Redes existentes com propriedade ou política divergentes são preservadas e
  bloqueiam a operação. Não se altera firewall do host nem redes de outros projetos.

## Consequências e limite de segurança

Não é necessário outro serviço de proxy para essa stack inicial. O web pode ter
saída de rede pela bridge: **não afirmamos airgap ou negação de egress do produto**.
Isso não provisiona infraestrutura externa nem fornece chaves para contratá-la.
Os serviços continuam locais, sem privilégios ou volumes de infraestrutura.

Se um produto exigir negar também a saída do serviço publicado, sua arquitetura
deverá qualificar uma camada de acesso/egress apropriada. Não se deve enfraquecer
o isolamento dos workers nem usar rede host como correção automática.

Esta é uma correção da hipótese do harness de homologação, fundamentada em
comportamento real. Não remove, ignora ou enfraquece testes do produto. A prova
que falhou e seus artefatos permanecem privados e não recebem aprovação retroativa.
