# Manutenção da distribuição

A distribuição atual contém o núcleo Hermes + Kanban, suas regressões, receitas
públicas, exemplos sem credenciais e procedimentos delimitados. Não contém os
controladores Multica, brokers, configurações pessoais, matrizes de calibração,
instaladores antigos e produtos descartáveis da fase anterior.

## Histórico e compatibilidade

A última referência anterior à limpeza é o commit
`bd9ad85e23624c0b9aa49507e3658049cce61557`. Consulte arquivos históricos pelo Git;
não os reative em paralelo com o runtime atual. Sem reescrita de histórico.

Em instalações existentes, arquivos retirados do índice podem permanecer locais,
ignorados, para preservar referências de imagem e recuperação. Esta limpeza não
promete liberar espaço do disco nem remove containers, volumes ou snapshots.
Os caminhos dos utilitários ainda usados e a lista fechada de exportação do
runtime foram preservados. A instalação ativa continua no seu export fixado.

## Critérios de retirada

Antes de retirar um componente, conferir imports, scripts, Docker COPY, CI,
contratos de exportação e documentação. Validar a árvore distribuída em uma pasta
limpa: testes no checkout antigo podem depender de arquivos ignorados.
Não remover regressões do núcleo atual para obter sucesso; testes de componentes
aposentados acompanham esses componentes no histórico.

## Novas contribuições

- Código reutilizável em src; regressões do núcleo em tests.
- Exemplos mínimos e sem estado privado em examples.
- Experimentos pessoais e recibos ficam fora do Git.
- Guias atuais não devem conter comandos para iniciar plataformas aposentadas.
- Relatórios históricos são referências datadas, não instruções operacionais.
- Rodar a verificação de publicação e testes em árvore limpa antes de publicar.
