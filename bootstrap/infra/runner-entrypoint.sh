#!/usr/bin/env bash
set -euo pipefail

state_dir="/actions-runner"
dist_dir="/opt/actions-runner-dist"

if [[ ! -x "${state_dir}/run.sh" ]]; then
  cp -a "${dist_dir}/." "${state_dir}/"
fi

cd "${state_dir}"

case "${1:-run}" in
  register)
    : "${RUNNER_URL:?RUNNER_URL não definido}"
    : "${RUNNER_TOKEN:?RUNNER_TOKEN não definido}"
    : "${RUNNER_NAME:?RUNNER_NAME não definido}"
    : "${RUNNER_WORKDIR:?RUNNER_WORKDIR não definido}"

    ./config.sh \
      --unattended \
      --replace \
      --disableupdate \
      --url "${RUNNER_URL}" \
      --token "${RUNNER_TOKEN}" \
      --name "${RUNNER_NAME}" \
      --labels "truco-local" \
      --work "${RUNNER_WORKDIR}"
    ;;
  run)
    if [[ ! -f .runner ]]; then
      echo "Runner ainda não registrado. Execute ./register-github-runner.sh." >&2
      exit 1
    fi
    # The listener must receive container stop signals directly. The shell
    # wrapper can leave the GitHub session alive until its lease expires.
    exec ./bin/Runner.Listener run
    ;;
  *)
    exec "$@"
    ;;
esac
