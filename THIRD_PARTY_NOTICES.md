# Código e dependências de terceiros

O código próprio está sob a licença MIT conforme `LICENSE`. Essa licença não substitui os termos de dependências, código externo ou trechos derivados de outros projetos.

Multica, Hermes, PostgreSQL/pgvector, Docker e bibliotecas Python/Node são dependências externas com termos próprios. Consulte os repositórios oficiais e a proveniência em `team-delivery-kit/evaluation/sources.lock.json` antes de redistribuir imagens. Essa lista não substitui um SBOM nem uma auditoria completa de licenças.

O runtime opcional `Dockerfile.quality-runner-base` combina imagens oficiais
Python e Node pinadas. A cópia seletiva de Node e das bibliotecas C++ preserva
os respectivos avisos em `/usr/local/share/licenses/quality-node/` na imagem;
isso não altera as licenças dessas dependências para MIT.

As skills vendorizadas da instalação original não são exportadas neste commit. Seus instaladores/provenance podem referenciar fontes externas, mas a redistribuição de cada skill depende de sua licença. Patches históricos preservados em `bootstrap/infra/patches/` também devem ser avaliados com a licença do projeto a que se aplicam.

## Correspondência de checks GitHub no caminho Hermes

A extensão de checks do commit integrado em `src/fabriquinha/publication.py`
adapta a política de `hermes_cli/kanban_pr_acceptance.py` do Hermes v0.22.0,
commit `e06df9c2eae6901f4c88f464e0ae6e753c0428b8`.
[Fonte original](https://github.com/NousResearch/hermes-agent/blob/e06df9c2eae6901f4c88f464e0ae6e753c0428b8/hermes_cli/kanban_pr_acceptance.py).
O classificador e a aceitação de PR são importados do upstream não modificado.
O aviso MIT correspondente é preservado abaixo:

```text
MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
