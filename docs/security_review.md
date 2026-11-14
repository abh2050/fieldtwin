# Security review

Date: 2026-11-14. Scope: everything in this repository as it runs locally (ADR 0022 removed cloud deployment): the FastAPI API, the web app, the PostGIS schema, the acquisition and processing pipelines, CI, and the repository itself. Evidence for each check is in the Gate 10 execution log unless stated.

## Threat model in one paragraph

FieldTwin holds no personal data and controls no equipment. Its data is public records plus synthetic data about a fictional field. The assets worth protecting are the **integrity of the evidence**: provenance, the audit trail, recorded results, and the claim that a decision was made by a person. Threats are therefore tampering, such as forging an approval, rewriting history, or substituting a result, and the ordinary web risks of a local app that someone might later expose. The system has to keep its integrity even when the application layer is wrong, which is why the most important controls are in the database.

## Controls and how they were checked

| Area | Control | Checked by |
|---|---|---|
| No physical actuation | No integration with any equipment exists. Work orders are records about fictional assets. | Design; no such dependency or code exists |
| Least privilege | The API connects only through `fieldtwin_app` (`SET ROLE`). That role can read, and can insert only into the human workflow tables. It cannot write source data, scenarios, alarms, recommendations, rules, or results, and it cannot disable triggers. Reads run in READ ONLY transactions. | `test_the_application_role_cannot_write_engine_or_source_tables`; ADR 0015 provenance tests |
| Decisions enforced in the database | Allowed transitions, role checks (only a maintenance supervisor approves), sequence and time ordering, "no status change without a transition and an audit event", and append-only history are all triggers and constraints. A compromised or buggy API still can't forge them. | 177 provenance-invariant tests, including direct attempts to bypass each rule |
| Authentication | Every state-changing endpoint needs a bearer token, checked before a database connection is opened. Only SHA-256 hashes of tokens are kept, and comparison is constant-time. Tokens are random, per role, and stored in git-ignored `.env.app` with mode 600. | Offline API tests (401 and 403 paths); smoke test |
| Authorization | Roles are checked in the API and again in the database. The UI only hides actions; it never authorizes. | API database tests: operator approval refused 403; viewer refused |
| Human versus scripted | `HUMAN`, `SCRIPTED_DEMO`, and `SYSTEM` are stored per transition. Only `SYSTEM` may create, and the UI labels scripted steps "not a person". | Database constraint `only_the_engine_creates`; web test |
| SQL injection | All values are bound parameters. Bandit's 11 "SQL built from strings" findings interpolate only constant column lists and WHERE clauses defined in code; each was read. | Bandit; `test_filters_are_parameters_not_sql` sends injection text through five filters |
| Path traversal | Result files, image chips, and the served web build resolve inside their root, and anything else is refused. Chip IDs must match a strict pattern. | `test_paths_outside_the_repository_are_refused`; `test_the_built_web_app_is_served_without_leaving_its_folder` |
| Replay and idempotency | An Idempotency-Key replays the first response and never acts twice. The same key with a different body is refused. Keys are scoped per caller. | API database tests |
| Error handling | One error shape with a correlation ID; no stack traces in responses; unhandled errors are logged server-side. | Offline tests |
| Logging | One JSON line per request with method, path, status, and latency. Tokens and request bodies are never logged. | Code review of `main.py`; the evidence scripts pass tokens through the environment so command logs never contain them (a leak into an earlier Gate 8 log was caught and the run redone) |
| Cross-origin | CORS allows only the local dev origins, and GET and POST. | Settings |
| Web content | Report markdown is rendered without raw HTML, and images in markdown are dropped. No `dangerouslySetInnerHTML`. The token lives in `sessionStorage` for the tab only. | Code review |
| Secrets in the repository | `.env` and `.env.*` are ignored; `.env.example` holds placeholders only. gitleaks scans the history in CI and the working tree in the clean-copy check. | gitleaks: no leaks |
| Dependencies | pip-audit on Python, and `npm audit` on production web dependencies at "high". Three web libraries were raised a major version in Gate 8 to clear advisories, one of them critical (MapLibre). | pip-audit: no known vulnerabilities; npm audit: 0 vulnerabilities |
| Supply chain in CI | GitHub Actions are pinned to commit SHAs, and workflow permissions are `contents: read`. | `ci.yml`; actionlint |
| Untrusted input | NM OCD arrives over plain FTP with no publisher checksum (Bandit flags `ftplib`). It is parsed with `expat` without external entities, never executed, validated row by row, and quarantined on failure. The raw batches are checksummed on arrival, which proves they haven't changed since, but not their origin. | Gate 1 tests; ADR 0003 |

## Findings

| # | Finding | Severity | Status |
|---:|---|---|---|
| 1 | `/health` used `assert` for control flow, which Python drops under `-O` | Low | Fixed in Gate 10 |
| 2 | Throwaway smoke-test tokens were written into a Gate 8 execution log through the logged command line | Low: the tokens were already dead | Fixed before that log was committed; tokens now pass through the environment |
| 3 | OCD's FTP source is unauthenticated and unencrypted | Inherent to the source | Accepted and documented; mitigated by parsing, validation, and checksums |
| 4 | Local bearer tokens have no expiry or rotation, and there is no rate limiting | Acceptable locally | On the [hardening roadmap](roadmap.md); must be fixed before any hosted use |
| 5 | The API serves over plain HTTP on 127.0.0.1 | Acceptable locally | It binds only to localhost; TLS is on the roadmap |
| 6 | The local database password is a development default | Acceptable locally | It binds to 127.0.0.1 only; documented in `.env.example` |

No high or critical finding is open.

## Not covered

No penetration test, fuzzing, or dynamic scan of the running web app was done. No review was done of a hosted configuration, because none exists.
