# Acceptance of an autonomous delivery

Use a useful release with two genuinely dependent increments after one approved
brief. Record a run identifier and the baseline source/configuration revisions.

Required evidence:
- Product produces the brief; the owner approves its exact revision.
- The team creates the dependency graph and assigns authors and independent reviewers.
- Each increment preserves previous tests and follows the applicable Red/freeze/Green contract.
- Negative controls demonstrate rejection of the protected behavioral defects.
- The second increment consumes the first accepted artifact and runs its regressions.
- PR review, CI, integration, deploy and QA refer to the exact accepted revisions.
- The final receipt includes a working local URL, commit, PRs and evidence of rollback.
- Any technical impediment is resolved by the team through a recorded diagnosis and handoff.
- No manual card edits, product/test patches, gate waivers or controller repairs occur after approval.

If operator intervention is necessary, preserve the cycle as assisted. Do not
reset counters or discard failed attempts to relabel it autonomous. A worker
running, a valid hold, or a passing suite alone is not completion.

Distribution is a separate qualification: repeat preparation from a clean clone
in an isolated installation, with private configuration, fixed dependencies and
verified backup/restore. A source cleanup or offline test pass is not that proof.
