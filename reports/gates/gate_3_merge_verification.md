# Gate 3 merge verification

Executed on 2026-11-05 against branch `gate-3`, before merging to `main`.

**Result: both merge conditions failed on first check.** They were fixed on the branch before merging ([ADR 0015](../../docs/adr/0015-application-role-and-provenance-chain.md)).

## Condition 1: an application can't bypass the domain boundary

No production application exists yet, so this was tested against the database role an application would have used.

| Attempt | Before | After, as `fieldtwin_app` |
|---|---|---|
| Edit or delete a `domain_boundaries` row | Allowed | Denied |
| Disable or drop the boundary trigger | Allowed | Denied |
| Enter replica mode, which skips triggers | Allowed | Denied |
| Become the table owner | Not applicable | Denied |
| Insert any `scenario_mappings` row | Stopped only by the trigger | Denied |
| Write observations, links, events, or runs | Allowed | Denied |

**Limit:** this verifies the role, not an application. Gate 8 has to connect the API through this role and test it. A superuser can still do anything, and DynamoDB (Gate 9) needs its own enforcement.

## Condition 2: every synthetic observation has a complete chain

The existing 8 series were complete, but the database didn't require that.

| Attempt | Before | After |
|---|---|---|
| Synthetic observation with no run | Accepted | Refused |
| Synthetic observation with no sensor | Accepted | Refused |
| Synthetic observation using a 3W sensor | Accepted | Refused |
| Source observation claiming a run | Accepted | Refused |
| Scenario differing from the run's | Accepted | Refused |
| Link naming the wrong asset | Accepted | Refused |

`v_synthetic_provenance_chain` reports each observation's asset, sensor, scenario, run, simulator version, and parameter set. The provenance audit now counts incomplete chains.

## Condition 3: the pull request passes CI

Recorded on the pull request.

## Tests

`tests/provenance/test_application_role.py` runs every attempt above against PostgreSQL. The escalation attempts use a genuine login connection, because a superuser session that switches roles with `SET ROLE` can always switch back and so wouldn't prove anything.
