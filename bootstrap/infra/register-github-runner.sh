#!/usr/bin/env bash
set -euo pipefail

infra_dir="/Users/weber/Documents/projetos_pessoais_desenv/hermes"
repo_slug="codifydeep/truco-online"

docker exec estudo-hermes gh auth status >/dev/null

runner_token="$(docker exec estudo-hermes gh api --method POST "repos/${repo_slug}/actions/runners/registration-token" --jq .token)"
trap 'unset runner_token' EXIT

RUNNER_TOKEN="${runner_token}" docker compose \
  --project-directory "${infra_dir}" \
  -f "${infra_dir}/compose.yaml" \
  --profile runner \
  run --rm github-runner register

unset runner_token

docker compose \
  --project-directory "${infra_dir}" \
  -f "${infra_dir}/compose.yaml" \
  --profile runner \
  up -d github-runner

echo "Runner local registrado e iniciado."

