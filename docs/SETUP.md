# Instalação segura e limites

## 1. Testes offline primeiro

Siga o README para criar um ambiente Python isolado e executar a suíte. Não são necessárias credenciais. Os checks públicos não executam os ensaios com modelos.

## 2. Plano de controle isolado

Docker Compose e acesso às imagens oficiais são necessários. Em `team-delivery-kit/`:

```bash
python evalctl.py init
python evalctl.py up
python evalctl.py verify
python evalctl.py status
```

Isso inicia somente PostgreSQL, backend e frontend do Multica, no grupo `delivery-kit-eval`. O frontend padrão é `http://localhost:19300` e a API `http://localhost:19080`. `init` gera `.local/evaluation.env` com permissões restritas; nunca o adicione ao Git.

Se essas portas ou o grupo já existirem, pare aqui: consulte a parametrização de `evalctl.py` antes de criar uma instalação distinta. Não sobreponha uma instalação existente.

```bash
python evalctl.py stop
```

`stop` preserva volumes. Não há motivo para usar `docker system prune`.

## 3. Agentes e execução

Não existe ainda um instalador genérico qualificado para toda a equipe. Antes de habilitar dispatch:

1. Escolha um repositório descartável, branch, contratos de testes e critérios de QA.
2. Gere imagens próprias a partir do código e confira a proveniência. Tags/digests locais de ensaios não são imagens públicas distribuídas.
3. Registre identidades, workspace e limites específicos da instalação.
4. Provisione a chave do modelo em armazenamento privado; não use automaticamente `provision_model_key.py`, que é um bridge específico do Hermes da instalação original.
5. Autorize conscientemente o socket Docker apenas para o controlador necessário.
6. Valide isolamento, revisão e recuperação antes de entregar trabalho de produto.

Não execute `compose.onboarding.yaml`, os overrides `port2` ou scripts de recuperação sem compreender seus efeitos. Alguns disparam chamadas cobradas, criam issues ou alteram GitHub. Relatórios e LaunchAgents da máquina original não são distribuídos; registro de serviços host exige configuração própria.

## Desktop Multica

O Desktop usa o endereço da **API**, não a porta do frontend. O arquivo `~/.multica/desktop.json` da versão avaliada suporta `schemaVersion`, `apiUrl`, `wsUrl` e `appUrl`. Consulte a documentação oficial da versão instalada antes de alterar; feche e reabra o app após mudanças.

Na instalação sem provedor de email, códigos temporários são registrados localmente. Não publique logs de autenticação. Na referência houve uma falha de atualização do stream de `docker logs`: não conclua que o pedido não chegou apenas por ausência nos logs; confira metadados no banco ou o retorno HTTP, sem expor segredos.
