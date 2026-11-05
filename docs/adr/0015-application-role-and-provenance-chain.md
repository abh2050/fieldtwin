# ADR 0015: Least-privilege application role and a required provenance chain

**Status:** Accepted and implemented before merging Gate 3.

## Context

Two merge conditions were tested against the Gate 3 branch, and both failed.

| Attempt, as the only configured database user | Result |
|---|---|
| Edit the `domain_boundaries` row | Allowed |
| Disable the boundary trigger | Allowed |
| Set `session_replication_role = replica`, which skips triggers | Allowed |
| Store a synthetic observation with no run | Allowed |
| Give an observation a scenario other than its run's | Allowed |
| Link a synthetic series to the wrong asset | Allowed |

That user is a superuser, as the PostGIS image creates it. Existing data was complete, but nothing required it to be.

## Decision

**Application role.** `fieldtwin_app` has no elevated attributes. It can read all tables, write only the human workflow tables, and update only `work_orders.status`. It can't change boundaries, rules, assessments, transformations, source data, scenario data, triggers, or schema. New tables default to read-only for it.

**Provenance chain.** The database now requires:

- A synthetic sensor is installed on one fictional asset.
- A synthetic observation has a run and a sensor, and only synthetic observations have a run.
- An observation's scenario is its run's scenario.
- An observation's sensor comes from its own source system.
- A link to a fictional asset names the asset the sensor is on, and the observation's scenario.

`v_synthetic_provenance_chain` shows the asset, sensor, scenario, run, simulator version, and parameter set for each synthetic observation, and the provenance audit counts incomplete chains.

## What this doesn't establish

- **No production application exists yet.** This verifies the role an application must use. Gate 8 has to connect the API through `fieldtwin_app`, with a test, or this protection doesn't apply.
- **The role is `NOLOGIN`.** Gate 8 or 9 grants login, with managed credentials.
- **Pipelines use the owner.** They run locally with owner rights, and they could bypass these controls if a person changes them. A separate pipeline role is future hardening.
- **A superuser can still do anything.** Nothing inside PostgreSQL can prevent that, so superuser access has to be restricted operationally.
- **DynamoDB has none of this.** The cloud read path (ADR 0002) needs its own enforcement, and Gate 9 must verify it.
