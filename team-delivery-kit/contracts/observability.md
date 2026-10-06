# Extensible roles and observability contract

Status: contract for future integration, NOT runtime enforcement or an installed analytics stack.

## Extension model

Roles are named configuration entries with responsibilities, capability requests,
reviewer/escalation references and permissions granted separately by the operator.
Adding a role must not require adding a branch to the coordinator's source code.
A role description, skill, memory entry or experiment result never grants permissions.
An agent cannot approve its own artifact or grant itself access to user data.

Keep execution state, curated engineering memory and product analytics separate.
Telemetry is evidence with provenance, not executable instructions or automatic authority.
No raw user traces, secrets or identifiable customer data in shared agent memory.

## Candidate future roles (disabled in phase 1)

- Observability engineer: telemetry conventions, instrumentation, operational and
  product event schemas, correlation and data-quality tests. Technical escalation to CTO.
- Product analyst / experimentation specialist: funnels, adoption, cohorts, hypotheses,
  A/B design and interpretation. Product decisions belong to Product/CEO, not this role alone.

These may be one or multiple profiles later. DevOps consumes operational telemetry;
Product consumes aggregated product evidence. Backend/data and frontend implement
instrumentation as part of the feature. QA verifies telemetry and experiment behavior.

## Feature instrumentation assessment

Every feature should record `required`, `not_needed` or `deferred`, with a rationale.
Assessment is required; emitting events for every feature is not.
When required, record:

1. Product hypothesis and/or operational risk; metric and intended decision.
2. Events/metrics/traces, schema version, units, emission point and accountable owner.
3. PII classification, minimization, lawful/consent requirements when applicable,
   access scope, retention and deletion. No secrets or raw request bodies by default.
4. Stable correlation without using user IDs as high-cardinality metric labels.
5. Tests for schema, duplicate/missing events, privacy and performance overhead.
6. Dashboard/query and whether alerting needs a responder and runbook.

Telemetry failure should not break the main feature unless the approved product
contract explicitly requires fail-closed behavior. Buffering must have bounds.

## Experiments (future)

An experiment requires an ID, hypothesis, primary metric, guardrails, assignment unit,
stable variant allocation, exposure event, eligibility, sample/duration rule and stop rule.
Record concurrent experiments and avoid changing the success metric after results arrive.
Small local demonstrations do not establish statistically reliable product conclusions.
QA covers both variants, disabled flag, data collection and rollback. Analysts may
recommend changes; production rollout remains subject to the delivery approval policy.

## Phase 1 scope

Reserve extensible roles and this decision contract only. Do not install analytics,
collect real user data, activate A/B tests, add paid services or broaden access now.
