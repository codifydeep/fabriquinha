#!/usr/bin/env bash
set -euo pipefail

container_name="estudo-hermes"
profiles=(
  produto
  designer
  cto
  techlead
  backend_data
  frontend
  mobile
  devops
  quality_security
)

if ! docker inspect "$container_name" >/dev/null 2>&1; then
  echo "Contêiner $container_name não encontrado." >&2
  exit 1
fi

read -r -p "Seu Telegram user ID numérico: " ceo_user_id
if [[ ! "$ceo_user_id" =~ ^[0-9]+$ ]]; then
  echo "User ID inválido: use somente algarismos." >&2
  exit 1
fi

read -r -p "Chat ID numérico do grupo Truco Online — Equipe: " group_chat_id
if [[ ! "$group_chat_id" =~ ^-?[0-9]+$ ]]; then
  echo "Chat ID inválido: use o identificador numérico, normalmente iniciado por -100." >&2
  exit 1
fi

echo
echo "Os tokens serão lidos sem eco e enviados ao contêiner por stdin."

for profile in "${profiles[@]}"; do
  read -r -s -p "Token do BotFather para $profile: " bot_token
  echo
  if [[ -z "$bot_token" ]]; then
    echo "Token vazio para $profile; nenhuma alteração adicional foi feita." >&2
    exit 1
  fi

  printf '%s' "$bot_token" | docker exec -i -u 10000:10000 \
    -e PROFILE_NAME="$profile" \
    -e CEO_USER_ID="$ceo_user_id" \
    -e GROUP_CHAT_ID="$group_chat_id" \
    "$container_name" sh -eu -c '
      profile_dir="/opt/data/profiles/$PROFILE_NAME"
      env_tmp="$profile_dir/.env.new"
      token="$(cat)"
      umask 077
      {
        printf "TELEGRAM_BOT_TOKEN=%s\n" "$token"
        printf "TELEGRAM_ALLOWED_USERS=%s\n" "$CEO_USER_ID"
        printf "TELEGRAM_HOME_CHANNEL=%s\n" "$GROUP_CHAT_ID"
        printf "TELEGRAM_ALLOWED_CHATS=%s\n" "$GROUP_CHAT_ID"
        printf "TELEGRAM_GROUP_ALLOWED_CHATS=%s\n" "$GROUP_CHAT_ID"
        printf "TELEGRAM_ALLOW_BOTS=mentions\n"
        printf "TELEGRAM_REQUIRE_MENTION=true\n"
        printf "TELEGRAM_EXCLUSIVE_BOT_MENTIONS=true\n"
      } >"$env_tmp"
      mv "$env_tmp" "$profile_dir/.env"
    '

  # Do not keep the legacy key: `config set` serializes the bracketed value as
  # a string (for example `'[-5584379349]'`), which makes the Telegram runtime
  # reject the real numeric chat ID. The canonical platforms.* list below is
  # parsed correctly; the environment CSV remains a compatible fallback.
  docker exec "$container_name" hermes -p "$profile" config unset telegram.allowed_chats >/dev/null 2>&1 || true
  docker exec "$container_name" hermes -p "$profile" config set telegram.group_allowed_chats "[$group_chat_id]" >/dev/null
  docker exec "$container_name" hermes -p "$profile" config set platforms.telegram.allowed_chats "[$group_chat_id]" >/dev/null
  docker exec "$container_name" hermes -p "$profile" config set platforms.telegram.group_allowed_chats "[$group_chat_id]" >/dev/null
  docker exec "$container_name" hermes -p "$profile" config set platforms.telegram.enabled true >/dev/null
  unset bot_token
done

docker restart "$container_name" >/dev/null

supervisor_ready=false
for _attempt in $(seq 1 30); do
  if docker exec "$container_name" hermes -p techlead gateway status >/dev/null 2>&1; then
    supervisor_ready=true
    break
  fi
  sleep 1
done

if [[ "$supervisor_ready" != true ]]; then
  echo "O supervisor Hermes não ficou pronto após o restart." >&2
  exit 1
fi

for profile in "${profiles[@]}"; do
  profile_started=false
  for _attempt in $(seq 1 5); do
    docker exec "$container_name" hermes -p "$profile" gateway start >/dev/null 2>&1 || true
    if docker exec "$container_name" python3 -c \
      'import json, sys; data = json.load(open(sys.argv[1])); sys.exit(0 if data.get("desired_state") == "running" else 1)' \
      "/opt/data/profiles/$profile/gateway_state.json" 2>/dev/null; then
      profile_started=true
      break
    fi
    sleep 2
  done

  if [[ "$profile_started" != true ]]; then
    echo "Não foi possível persistir o estado running para $profile." >&2
    exit 1
  fi
done

all_connected=false
for _attempt in $(seq 1 60); do
  connected=0
  for profile in "${profiles[@]}"; do
    if docker exec "$container_name" python3 -c \
      'import json, sys; data = json.load(open(sys.argv[1])); telegram = data.get("platforms", {}).get("telegram", {}); sys.exit(0 if telegram.get("state") == "connected" else 1)' \
      "/opt/data/profiles/$profile/gateway_state.json" 2>/dev/null; then
      connected=$((connected + 1))
    fi
  done
  if [[ "$connected" -eq "${#profiles[@]}" ]]; then
    all_connected=true
    break
  fi
  sleep 2
done

if [[ "$all_connected" != true ]]; then
  echo "Nem todos os gateways conectaram ao Telegram dentro de 120 segundos." >&2
  docker exec "$container_name" hermes profile list >&2 || true
  exit 1
fi

echo
echo "Telegram configurado e os nove gateways estão conectados:"
docker exec "$container_name" hermes profile list
