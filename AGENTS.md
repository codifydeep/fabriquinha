# Docker operating contract

## Source control and public distribution

- The automation source is versioned at `https://github.com/codifydeep/fabriquinha`.
  Keep code, tests, contracts and public documentation in Git as changes evolve.
- Never add private installation state, secrets, model conversations, operational
  diaries, snapshots, databases or product worktrees. Run
  `python3 scripts/check_publication.py` on the staged content before publishing.
- Update the public README diagrams and qualification boundaries when the actual
  architecture changes. Do not imply Temporal or complete autonomy is implemented
  unless the installed code and end-to-end evidence support that statement.
- Preserve runtime paths during source reorganization; image COPY paths and
  authorization hashes are part of the operational contract. Use reviewed PRs
  for subsequent changes instead of unrelated product repositories.

- Every new project container must appear in a Docker Desktop Compose group.
  Use Docker Compose for persistent services. For controller-created disposable
  containers, use `team-delivery-kit/docker_grouping.py` (`args` or
  `grouped_create`), including project, service, oneoff and lifecycle labels.
- Group delivery-kit core services as `delivery-kit-<instance>`, disposable
  workers/probes as `delivery-kit-<instance>-tests`, and deployed candidates as
  `delivery-kit-<instance>-homologation`. Never use random ungrouped names.
- Prefer `--rm` for synchronous disposable jobs. Where durable inspection is
  required, archive evidence before retiring the exact owned stopped container.
- Do not use global prune, delete volumes or clear snapshots as routine cleanup.
  Confirm no active leases, resolve exact IDs, preserve logs and temporary data,
  revalidate ownership immediately before removal, and observe uncertain Docker
  deletion acknowledgments without blindly repeating them.
- Preserve current deployment and core services. Never alter `toso-*`, `reforma`
  or unrelated projects during delivery-kit cleanup. Never print credentials or
  complete Docker inspect environment data; private archives use restricted modes.
- Image cleanup is explicit and scoped: preserve every `toso-*` tag and any
  aliases sharing its image ID, all container-used images, source-referenced
  builds/digests and two recent versions per owned image family for rollback.
  Revalidate tags/IDs and container use before deletion. Use no force and no
  parent-image pruning; never infer ownership of untagged/dangling images.
