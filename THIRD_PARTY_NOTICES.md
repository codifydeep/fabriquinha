# Código e dependências de terceiros

O código próprio está sob a licença MIT conforme `LICENSE`. Essa licença não substitui os termos de dependências, código externo ou trechos derivados de outros projetos.

Hermes, Docker, Python, Playwright e Chromium têm licenças próprias. Consulte os
repositórios oficiais, as versões fixadas nos requisitos e as imagens base antes
de redistribuir binários. Esta lista não substitui SBOM ou auditoria de licenças.

O código legado Multica e os patches da instalação anterior foram retirados da
distribuição atual. Seus avisos e proveniência permanecem no histórico Git;
recuperar código histórico também exige preservar as respectivas licenças.

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
