# Production-hardening roadmap

What would have to change before FieldTwin, or a system built like it, ran against a real field with real users. It is ordered by what blocks what. Nothing here is built. Cloud hosting was removed from this project's scope (ADR 0022), so hosting items are written as requirements, not as plans to deploy.

## 1. Earn the capability first

Hardening a weak capability is wasted effort. The project's own evidence says detection and alarm-driven dispatch don't yet pay, so these come first.

1. **Calibrate against a real system.** Fit the network model to a real gathering system's measured pressures and flows, with uncertainty, before trusting any synthetic result.
2. **Test on real faults.** Build a labelled set of real restrictions and equipment failures from the target field's maintenance records. Preregister the evaluation as D1 was.
3. **Fix D1's failure modes.** Marginalize over missing telemetry instead of assuming it. Treat compressor state as unknown. Widen intervals at high severity. Re-run with a new preregistration, without reusing D1's final cases.
4. **Only then test whether alarm-driven dispatch beats fixed rounds,** using that field's costs.

## 2. Identity, access, and audit

- A managed identity provider with single sign-on and MFA, replacing local bearer tokens.
- Short-lived tokens, and server-side sessions with revocation.
- Roles from the identity provider, mapped to the existing VIEWER, OPERATOR, and MAINTENANCE_SUPERVISOR. The database role checks stay as the backstop.
- Ship audit events to append-only storage outside the database, for example WORM object storage, so that a database administrator couldn't rewrite history unnoticed.
- Separation of duties: the person who opens a work order can't approve it. This would become a database rule.

## 3. Serving

- TLS everywhere, a reverse proxy, security headers, and a content security policy for the web app.
- Rate limiting and request-size limits per caller.
- Managed PostgreSQL with backups, point-in-time recovery, and tested restores. Read replicas for the dashboards.
- Secrets in a secrets manager, with no default passwords.
- Separate environments with promotion between them, and migrations applied by the pipeline, never by hand.

## 4. Data pipelines

- Scheduled, idempotent acquisition with alerting on failure, schema drift, and row-count anomalies.
- Signed or checksummed sources where the publisher offers them; quarantine and alert when one changes unexpectedly.
- A real-time ingestion path, such as OPC UA or MQTT through a historian, for live telemetry. The current system replays stored runs only.
- Data retention and deletion policies per source licence.

## 5. Models and decisions

- A model registry with approval before deployment, and shadow mode before any recommendation reaches a person.
- Monitoring of alarm rates, drift, and calibration, with automatic fallback to rule-based alarms.
- Every recommendation keeps its full evidence chain, as it does now, and the decision engine stays deterministic and explainable.
- Recommendations stay advisory. No path to equipment control without a separate safety case.

## 6. Operations

- Structured logs, metrics, and traces with correlation IDs (already in place), shipped to a central store, with alerts and runbooks.
- A browser end-to-end test suite in CI, including real WebGL map rendering.
- Load tests for the telemetry endpoints, and pagination or streaming for long series.
- Accessibility audit (WCAG 2.2 AA) and usability testing with operators.
