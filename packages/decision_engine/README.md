# packages/decision_engine

Gate 7 decision support for fictional AETHER Field (ADR 0019).

| Module | Purpose |
|---|---|
| `topology.py` | Locations and consequence shares, derived from the Gate 4 network graph |
| `rules.py` | The rule engine: one detector alarm in, one explained recommendation out. Scores are sums of named terms, never probabilities. |
| `workflow.py` | Work-order states, allowed transitions, actors, and the audit trail. The engine only recommends. |
| `economics.py` | The modeled comparison of fixed, risk-based, and route-optimized scheduling |
