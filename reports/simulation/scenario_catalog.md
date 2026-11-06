# Scenario configuration catalog

Generated from [`config/scenarios/aether_field_scenarios.yaml`](../../config/scenarios/aether_field_scenarios.yaml) and [`config/facility/aether_network.yaml`](../../config/facility/aether_network.yaml). A test fails if this file differs from a fresh run.

> **All values are `SYNTHETIC`.** AETHER Field is a fictional industrial production environment. These results come from a simplified physical model of fictional equipment. They are not real operating data, and the model is not a validated engineering simulator.

## Common settings

| Setting | Value |
|---|---|
| Random seed | 40012 |
| Sampling | 300 s for 7 days |
| Simulated clock starts | 2040-01-01T00:00:00+00:00, in the future so it can't pass for real operations |
| Simulator | aether-field-network, version 1 |

## Scenarios

| Scenario | Name | Category | Target | Affected | Changes physics | Parameter set SHA-256 |
|---|---|---|---|---|---|---|
| `AETHER-NET-NORMAL` | Normal production | NORMAL | GATHERING | GATHERING | no | `339918f63c43dc51...` |
| `AETHER-FAULT-001-NET` | Progressive gathering-line restriction | PHYSICAL_FAULT | A-03 | GS-A | yes | `8af783b79fa97838...` |
| `AETHER-NET-COMPRESSOR-DERATE` | Compressor capacity reduction | PHYSICAL_FAULT | C-01 | COMP-STATION | yes | `c72d775ec0efb21d...` |
| `AETHER-NET-SENSOR-DRIFT` | Sensor bias and drift | SENSOR_FAULT | A-03 | GS-B | no | `ab94449d43007a29...` |
| `AETHER-NET-COMM-DROPOUT` | Communication dropout | COMMUNICATION_FAULT | HDR-B | PAD-B | no | `93175e73d94ca488...` |
| `AETHER-NET-PLANNED-SHUTDOWN` | Planned equipment shutdown | PLANNED_OPERATION | GS-B | PAD-B | yes | `4909abb7d01ee6e7...` |

## Scheduled actions

### `AETHER-NET-NORMAL`

All wells produce with every compressor available.

No scheduled actions.

### `AETHER-FAULT-001-NET`

A restriction develops in GS-A, on the path shared by all Pad A wells.

| Action | Asset or tag | Starts | Duration | Amount |
|---|---|---|---|---|
| SEGMENT_RESTRICTION | GS-A | day 2.00 | ramp ends day 6.00, then holds | severity 0.65 |

### `AETHER-NET-COMPRESSOR-DERATE`

C-01 progressively loses capacity until the station can't take all arrivals at setpoint.

| Action | Asset or tag | Starts | Duration | Amount |
|---|---|---|---|---|
| COMPRESSOR_DERATE | C-01 | day 2.00 | ramp ends day 4.00, then holds | capacity fraction 0.3 |

### `AETHER-NET-SENSOR-DRIFT`

Two instruments report wrongly while the physical process doesn't change.

| Action | Asset or tag | Starts | Duration | Amount |
|---|---|---|---|---|
| DRIFT | A-03.PT-WH | day 2.00 | continues to the end | 5000 Pa per day |
| BIAS | GS-B.DPT-NET | day 3.00 | continues to the end | 8000 Pa |

### `AETHER-NET-COMM-DROPOUT`

Readings from Pad B and C-02 stop arriving for a time while the process continues.

| Action | Asset or tag | Starts | Duration | Amount |
|---|---|---|---|---|
| COMMUNICATION_DROPOUT | PAD-B | day 3.00 | ends day 3.50 | readings not received |
| COMMUNICATION_DROPOUT | C-02 | day 5.00 | ends day 5.25 | readings not received |

### `AETHER-NET-PLANNED-SHUTDOWN`

Pad B is isolated with C-04 stopped for maintenance, and later one well is shut in.

| Action | Asset or tag | Starts | Duration | Amount |
|---|---|---|---|---|
| CLOSE_VALVE | IV-B | day 3.00 | ends day 3.50 | planned |
| STOP_COMPRESSOR | C-04 | day 3.00 | ends day 3.50 | planned |
| SHUT_IN_WELL | A-02 | day 5.00 | ends day 5.50 | planned |

## Separation of fault kinds

A scenario declares one category, and the contract refuses mixed ones. Sensor and communication faults are applied after the solve, so they can't change the physics, and a test confirms their truth tables equal the normal case.
