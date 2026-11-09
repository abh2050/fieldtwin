# packages/anomaly_detection

Anomaly detectors, evaluated in Gate 5 under rules fixed before fitting ([ADR 0017](../../docs/adr/0017-detection-evaluation-design.md)).

| Module | Purpose |
|---|---|
| `labels.py` | 3W label audit: fully labeled, partially labeled, or ambiguous, and which metrics an instance can enter |
| `splits.py` | Well-grouped folds, with a check that no well is on two sides |
| `features.py` | Causal window statistics: mean, spread, slope, and fraction missing |
| `detectors.py` | Static limits, rolling deviation, logistic regression, isolation forest, and gradient boosting |
| `evaluation.py` | Alarm episodes, event matching, false alarms, chance level, cluster bootstrap, and method selection |
| `contracts.py` | Streaming request and prediction contracts, with no field for fault truth |
| `inference.py` | Streaming engine, sharing the batch feature and alarm code |

Nothing here imports the simulator or the label files, and a test enforces this.
