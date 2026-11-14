# ADR 0021: Resume Gates 8 to 10 after D1

**Status:** Accepted, 2026-11-12.

## Context

ADR 0020 paused Gates 8 to 10 and said they would resume only by a later decision citing D1's outcome. D1 was evaluated on 2026-11-11 and concluded **NOT MET** ([final report](../../reports/diagnostics/final_report.md)):

- In-regime, every preregistered line passed except measurement top-1 gain (0.008 against at least 0.08). Top-1 was 0.992, against 0.578 for the residual baseline.
- Held-out, three of six regimes failed lines: high severity (interval coverage), compressor outside its trained range (impact coverage), and degraded operations (top-1 0.412).

The project now has eight gates of evidence, including three negative results (Gate 5 detection, Gate 7 modeled economics, D1), and nothing a person can use without reading reports and running scripts.

## Decision

1. **No further research milestones are planned.** D1's result stands as recorded; nothing is retuned or rerun.
2. **Gates 8 to 10 resume** in their original order: the application, the AWS deployment, then the portfolio package.
3. **The application presents existing results as they are.** It reads the database and committed reports. It shows negative results with the same prominence as positive ones, labels every synthetic value, and invents no metric. D1 appears as an experiment report, not as a product capability.
4. **Scope is the specification's sections 14 and 15**, connected through the `fieldtwin_app` role (ADR 0015). Scripted demonstration approvals stay labelled `SCRIPTED_DEMO`.
5. **Gate 9 still needs explicit approval** before any AWS resource is created.

## Consequences

- The detector, the decision rules, and D1's method stay as evaluated. The app is a window onto them, not an improvement of them.
- Any future research would need its own ADR and preregistration; none is proposed.
