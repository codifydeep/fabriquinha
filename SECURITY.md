# Segurança

Esta plataforma é experimental. Não execute código de agentes em host com segredos ou cargas de produção. O socket Docker confere poder amplo sobre o host; o controlador é uma fronteira privilegiada, não uma sandbox contra si mesmo.

## Nunca versionar

- Chaves LLM/GitHub/Telegram, JWTs, códigos de login, PATs e `.env` privados.
- Bancos, sessões, memória privada, snapshots, transcrições, logs e volumes.
- Credenciais copiadas de uma instalação Hermes existente.

`.gitignore` não protege arquivos já rastreados. O check de publicação inspeciona o conteúdo do Git e bloqueia padrões comuns; não substitui revisão nem garante detectar todo segredo.

Não exponha o Multica de avaliação na Internet: a configuração de referência usa loopback, não oferece uma implantação TLS/rate-limit de produção e pode imprimir códigos de login em logs locais.

Ao encontrar uma vulnerabilidade com segredo, não abra issue pública com o valor. Use o canal privado de segurança do GitHub, se habilitado, ou contate o proprietário sem anexar credenciais. Revogue segredos antes de limpar o histórico; não reescreva histórico sem autorização.
