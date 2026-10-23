# Código e dependências de terceiros

O código próprio está sob a licença MIT conforme `LICENSE`. Essa licença não substitui os termos de dependências, código externo ou trechos derivados de outros projetos.

Multica, Hermes, PostgreSQL/pgvector, Docker e bibliotecas Python/Node são dependências externas com termos próprios. Consulte os repositórios oficiais e a proveniência em `team-delivery-kit/evaluation/sources.lock.json` antes de redistribuir imagens. Essa lista não substitui um SBOM nem uma auditoria completa de licenças.

O runtime opcional `Dockerfile.quality-runner-base` combina imagens oficiais
Python e Node pinadas. A cópia seletiva de Node e das bibliotecas C++ preserva
os respectivos avisos em `/usr/local/share/licenses/quality-node/` na imagem;
isso não altera as licenças dessas dependências para MIT.

As skills vendorizadas da instalação original não são exportadas neste commit. Seus instaladores/provenance podem referenciar fontes externas, mas a redistribuição de cada skill depende de sua licença. Patches históricos preservados em `bootstrap/infra/patches/` também devem ser avaliados com a licença do projeto a que se aplicam.
