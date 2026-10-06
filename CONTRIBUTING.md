# Contribuindo

1. Abra issue com objetivo e critério verificável; use `codex/` para branches criadas pelo Codex.
2. Escreva o teste que demonstra a falha antes de implementar; documente Red, Green e suíte completa no PR.
3. Não exclua, ignore ou enfraqueça testes existentes para obter CI verde.
4. Não misture mudanças do controlador com alterações do produto de um ensaio.
5. Exija revisão independente e mantenha aprovações vinculadas ao SHA/snapshot correto.
6. Execute `python scripts/check_publication.py` e a suíte offline antes de publicar.

Não execute scripts de ensaio com credenciais reais nos checks públicos. Workflows não têm acesso ao Docker do host, ao LLM ou a credenciais de GitHub além do token read-only de checkout. Novos containers locais seguem o contrato de `AGENTS.md`.

Ative o guard local antes de trabalhar: `git config core.hooksPath scripts/hooks`. O hook valida o conteúdo preparado no index antes do commit; o mesmo check roda na CI. Evite `--no-verify`.

Não mova módulos existentes sem atualizar imports, Dockerfiles, fixtures, hashes de autorização e os testes correspondentes. O layout atual é uma interface operacional; uma reorganização física exige migração separada.
