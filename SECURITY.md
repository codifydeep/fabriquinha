# Segurança

Esta plataforma é experimental. Não execute código de agentes em host com segredos ou cargas de produção. O socket Docker confere poder amplo sobre o host; o controlador é uma fronteira privilegiada, não uma sandbox contra si mesmo.

## Nunca versionar

- Chaves LLM/GitHub/Telegram, JWTs, códigos de login, PATs e `.env` privados.
- Bancos, sessões, memória privada, snapshots, transcrições, logs e volumes.
- Credenciais copiadas de uma instalação Hermes existente.

`.gitignore` não protege arquivos já rastreados. O check de publicação inspeciona o conteúdo do Git e bloqueia padrões comuns; não substitui revisão nem garante detectar todo segredo.

Não exponha o Multica de avaliação na Internet: a configuração de referência usa loopback, não oferece uma implantação TLS/rate-limit de produção e pode imprimir códigos de login em logs locais.

No caminho Hermes novo, a stack de homologação Python/HTTP publica o web somente
em loopback. A bridge do web permite egress: não é um produto airgapped. O
navegador de QA fica em rede interna própria e recebe apenas driver e contrato
congelado somente leitura; os jobs de suíte ficam sem rede. Nenhum desses jobs
recebe socket, banco do controlador ou credenciais de infraestrutura por mounts.
Essa prova usa autores/GitHub sintéticos e não constitui certificação de segurança
ou autonomia. Consulte os limites e o [ADR 0002](docs/ADR-0002-LOCAL-WEB-AND-QA-NETWORKS.md).

A ponte nativa executa o SDK no processo confiável do adaptador; não há isolamento
de SO entre esse SDK e o controlador. Apenas código/comandos gerados rodam na
sandbox Docker, sem socket, banco ou credenciais por mounts. A política que limita
handlers do registry exige um processo dedicado por claim: nunca habilitá-la em
gateway multiplexado. O Hermes fixado e os plugins aprovados do adaptador são
parte da base confiável; não carregar plugins fornecidos pelo produto gerado.
O serviço novo reconstrói uma sandbox antiga somente para retirada, após conferir
run e identidade do processo morto. Isso não restaura a autoridade da claim.
Uma segunda invocação de worker sobre o mesmo run é recusada sem bloquear o dono.
O arquivo privado da rota não pode ser público ou symlink; a entrada operacional
atual recusa projeto de produção, sem levantar automaticamente a pausa do provedor.
Diagnósticos técnicos leem snapshots imutáveis e executam experimentos somente
em cópias descartáveis, com os mesmos testes protegidos e isolamento dos jobs.
O técnico não escreve no autor, aprova produto ou dispensa gates. Sua decisão
tipada pode orientar uma retomada, que precisa passar novamente pela qualidade.
Notificações usam apenas identidades e textos fixos, não código/erros brutos.
A rota privada não é montada nos workers. Telegram usa host HTTPS fixo, não segue
redirects e não habilita broadcasts pagos. ACK incerto fica visível, sem reenvio
cego; a consulta por chave do sink de teste não é atribuída ao Telegram real.

Ao encontrar uma vulnerabilidade com segredo, não abra issue pública com o valor. Use o canal privado de segurança do GitHub, se habilitado, ou contate o proprietário sem anexar credenciais. Revogue segredos antes de limpar o histórico; não reescreva histórico sem autorização.
