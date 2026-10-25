# TDD de frontend com navegador real — 25 de outubro de 2026

## Problema encontrado no S4 real

A arquitetura aprovada previa interação client-side. A imagem de validação,
porém, continha Python/unittest sem engine JavaScript ou navegador. Chromium
existia somente no QA depois do deploy. O autor escreveu testes sobre palavras
do HTML/JS; o revisor recusou corretamente sua equivalência a comportamento.
Revisões sucessivas não resolveram a lacuna, e a cota do ensaio terminou.

Não houve implementação integrada nem homologação. O brief não será reduzido
para contornar o problema, e testes de strings não serão aprovados como prova
da interação. Os snapshots e pareceres permanecem privados e recuperáveis.

## Correção: mesma suíte, capacidade explícita

`browser_tdd: true` é uma capacidade opcional do projeto. Sem a opção, a
identidade dos projetos antigos permanece igual. Com ela, a imagem deve ter
o rótulo `fabriquinha.browser-tdd=1`, além do mesmo usuário sem privilégios,
entrypoint fixo e ausência de volumes embutidos exigidos pelo executor.

O comando continua `python -B /opt/fabriquinha/suite.py`, com descoberta unittest
completa. Testes podem usar `playwright.sync_api` e Chromium contra seu próprio
servidor HTTP temporário. Isso vale para Red, Green, controles negativos,
revisão e CI: não é outro pipeline ou scheduler.

O perfil de navegador limita cada job a 512 MiB, uma CPU, 128 PIDs e `/tmp`
temporário de 128 MiB. Permanecem rede `none`, entrega somente leitura, usuário
`65534`, capabilities removidas e nenhum socket/credencial de infraestrutura.
O máximo de dois workers não muda. O runtime da aplicação continua Python
stdlib: Playwright é dependência dos testes, não algo a importar no produto.

O contexto anuncia as ferramentas realmente disponíveis. Explica Red por
assertion, não por timeout de seletor/import ausente. Autor/revisor podem fixar
seletores e texto determinístico nas escolhas delegadas pelo brief; isso não é
uma nova decisão do CEO. A especificação declarativa do QA pós-deploy continua
fechada; não inventar operações que seu executor não suporta.

## Imagem local e limites de reprodução

`Dockerfile.validation-browser` reaproveita a base de navegador já instalada,
agora identificada por **tag e digest juntos**, e adiciona somente o reporter
confiável. A imagem construída foi conferida contra o ID da base antes/depois.
Não houve instalação de pacotes ou download de camadas. O primeiro uso da
referência somente por digest tentou resolver um nome local no registry e falhou;
não foi tratado como imagem construída. A receita tag+digest passou no check do
BuildKit sem avisos.

```sh
docker build --network=none --pull=false \
  -f Dockerfile.validation-browser \
  -t delivery-kit-validation-browser:LOCAL_VERSION .
```

A base citada ainda é uma dependência do cache da instalação de referência.
Isso **não** é S6/instalação limpa qualificada. Ainda falta provisionar uma base
pública/reproduzível, com licenças e versões travadas, em máquina sem esse cache.
Não reaproveitar dados, containers ou configurações do projeto Reforma: somente
a imagem de navegador anteriormente derivada para delivery-kit foi lida.

## Prova física

`scripts/qualify_browser_tdd.py` usa um contador descartável, não a feature de
saudação do S4, e executou quatro jobs reais:

1. Baseline HTTP anterior passando.
2. Novo teste de DOM falhando por assertion após clicar no botão.
3. Freeze independente programado; Green com os mesmos bytes de testes.
4. Controle negativo contendo as palavras esperadas no código, mas sem efeito
   na página: o teste de navegador falha novamente.

O teste também verificou usuário, ausência de socket/variáveis de credencial e
recusa real de escrita na entrega. Os jobs foram arquivados/retirados. Não houve
inferência, rede externa, GitHub, nova implantação ou volume apagado.

O freeze é programado: esta prova não demonstra julgamento de modelo ou ciclo
nativo completo. A nova instalação precisa produzir testes/revisões próprios;
nenhuma aprovação ou evidência TDD das tentativas anteriores é convertida.

## Fronteiras restantes

- Novo S4 com modelo, revisão independente, PR/CI, deploy/QA e rollback completos.
- A [escalada explícita de revisão](HERMES-RECOVERY-QUALIFICATION.md#escalada-explícita-de-revisão--25102026)
  ao CTO passou no SDK/Kanban com respostas locais programadas. O modelo ainda
  precisa reconhecer quando usá-la; não há detector semântico geral de loops.
- Memória/segunda release, falhas S5, instalação/segundo repositório S6 e Truco S7.

Capacidade de executar testes reais não garante que o modelo os escreverá bem.
Revisão semântica independente e controles negativos continuam obrigatórios.
