# ADR 0010: Keep 3W as a separate benchmark, and plan synthetic AETHER telemetry

**Status:** Accepted, and implemented by ADRs 0012 and 0014. Gate 3 tightened decision 2: no 3W event is mapped onto AETHER, even with an allowing assessment.

## Context

The original demonstration replayed a 3W event against a fictional AETHER well. 3W describes offshore oil wells with subsea trees and gas lift, while AETHER is an onshore gas field. The compatibility assessment found no directly compatible variable or event class ([report](../../reports/reconciliation/semantic_compatibility.md)).

## Decision

1. 3W remains a separately identified offshore anomaly-detection benchmark, evaluated on its own labels and wells.
2. No 3W measurement maps directly to AETHER equipment. Any experimental use requires an assessment that allows it, plus evidence for each condition.
3. AETHER telemetry will come from a future physics-constrained synthetic capability, labeled `SYNTHETIC`.

A later gate should scope that capability, including at least:

- Declared gas composition, well geometry, and choke characteristics.
- Mass and energy balance constraints, and compressible flow through the choke.
- Fault models written as physical mechanisms, with stated assumptions.
- Deterministic seeds, and validation against physical bounds.
- No claim that synthetic results measure performance on real wells.

## Consequences

- AETHER-FAULT-001 needs revision before Gates 3 to 5 rely on it. This changes section 22 of the specification.
- A model evaluated on 3W shows method capability on 3W. That result can't be presented as AETHER performance.
- A synthetic generator can reflect its own assumptions, so detection results on it are a demonstration, not a benchmark.
