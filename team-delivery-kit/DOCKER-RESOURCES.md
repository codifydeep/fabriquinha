# Docker resource organization

Docker Desktop groups containers by Compose project, not filesystem folders.

- Core infrastructure: `delivery-kit-port2` (or the selected instance name).
- Disposable workers, seeds, locks, frozen suites, browser fixtures and probes:
  `<instance>-tests`.
- Persistent local homologation applications: `<instance>-homologation`.

Controller-created containers must use `docker_grouping.labels` at the Docker
API creation boundary or `docker_grouping.args` for CLI creation. Preserve
ownership, issue, source task and source SHA labels; grouping is presentation,
not authorization. Test jobs are kept outside the core Compose project so an
orphan cleanup cannot accidentally mix jobs with runtime/database services.
One-shot jobs must be removed in their existing validated cleanup/finally paths.

Never use global `docker system prune`, remove all stopped containers, delete
volumes based on names alone, or touch `toso-*`. Before retiring historical
applications, verify no workers are active and preserve logs, inspect metadata,
SQLite backups and durable delivery receipts. Core and latest homologation are
excluded. Existing images, workspaces, snapshots and volumes remain available.

## Local administration: 2026-10-01

Removed 26 historical standalone test applications. Backups:
`.local-port2/backups/container-cleanup-20261001-112314/`.
All other containers were checked against the original inventory. The latest
application was separately recreated for grouping; its database and immutable
image were preserved. Its migration receipt is in
`.local-port2/backups/homologation-grouping-yt69_d_b/`.

Latest app: `delivery-kit-port2-browserfix-2-qa`, port `19438`, managed by:

```sh
docker compose -p delivery-kit-port2-homologation -f compose.homologation-port2.yaml ps
```

The local Compose file deliberately reuses the existing external data volume.
Do not use it as a portable application template on another host.
The container ID changed: historical QA receipts remain historical and are not
rewritten as fresh validation. Future browser qualification must verify the new
deployment identity through its normal gate.

Installed broker image `delivery-kit-eval-broker:20261001.15` applies grouping to
every container it creates. Legacy core instance `delivery-kit-eval` remains
available, unchanged; new autonomous runs use `delivery-kit-port2`.
