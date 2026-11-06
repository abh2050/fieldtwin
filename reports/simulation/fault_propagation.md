# Cross-asset fault propagation

Each expected direction is derived from the asset's place in the declared topology, before results are read. It is then compared with the coupled solve. A test fails if this file differs from a fresh run, or if any direction disagrees.

> **All values are `SYNTHETIC`.** AETHER Field is a fictional industrial production environment. These results come from a simplified physical model of fictional equipment. They are not real operating data, and the model is not a validated engineering simulator.

## Result

**81 of 81 topology-based predictions matched the coupled solve in direction.** This confirms the solver and the topology reasoning agree with each other. It doesn't show that a real gathering system would behave this way, and magnitudes depend on chosen parameters.

## How one fault reaches other assets

1. **Restriction in GS-A.** Pad A's header pressure rises, so every Pad A well loses drawdown and flow. Less gas enters the trunk, which lowers its friction loss, so manifold pressure falls. Pad B then discharges into a lower pressure and gains flow. Suction stays at setpoint, so compressors see only the smaller total.
2. **Capacity loss on C-01.** Once arrivals exceed capacity, suction floats above setpoint. That pressure carries back through the trunk and manifold to every well on both pads, and the other units take a larger share.
3. **Isolation of Pad B.** Its wells stop, and the trunk carries about half the gas. Lower friction lets Pad A wells produce more. Stopping C-04 at the same time doesn't limit flow, because arrivals fell by more than its capacity.

The model is quasi-steady, so these effects appear in the same sample. Real pressure transients take time to travel, and that isn't modeled.

## Restriction in GS-A

`AETHER-FAULT-001-NET` against `AETHER-NET-NORMAL`, at day 7.00. Flows in sm3/s, and pressures in Pa absolute.

| Asset | Quantity | Baseline | Faulted | Change | Expected | Observed | Why |
|---|---|---:|---:|---:|---|---|---|
| HDR-A | Header pressure | 1,903,667 | 2,244,709 | +17.91% | rises | rises | Upstream of the restriction. More resistance in GS-A needs a higher inlet pressure to pass gas. |
| GS-A | Flow | 3.5867 | 2.9447 | -17.90% | falls | falls | Its wells can't push as much gas against the added resistance. |
| MANIFOLD | Manifold pressure | 1,720,183 | 1,700,823 | -1.13% | falls | falls | Less gas reaches GS-TRUNK, so its friction loss falls and the manifold relaxes toward suction. |
| GS-TRUNK | Flow | 7.1181 | 6.5006 | -8.68% | falls | falls | The rise from the other pad is smaller than the loss from the restricted pad. |
| COMP-SUCTION | Suction pressure | 1,600,000 | 1,600,000 | +0.00% | unchanged | unchanged | Recycle holds setpoint, because capacity still exceeds arrivals. |
| A-01 | Gas flow | 0.6117 | 0.5105 | -16.55% | falls | falls | Shares the restricted path, so higher backpressure reduces its drawdown. |
| A-01 | Wellhead pressure | 1,929,348 | 2,259,924 | +17.13% | rises | rises | Backpressure from its header rises. |
| A-02 | Gas flow | 0.5688 | 0.4530 | -20.35% | falls | falls | Shares the restricted path, so higher backpressure reduces its drawdown. |
| A-02 | Wellhead pressure | 1,923,783 | 2,255,563 | +17.25% | rises | rises | Backpressure from its header rises. |
| A-03 | Gas flow | 0.6415 | 0.5488 | -14.45% | falls | falls | Shares the restricted path, so higher backpressure reduces its drawdown. |
| A-03 | Wellhead pressure | 1,926,544 | 2,258,948 | +17.25% | rises | rises | Backpressure from its header rises. |
| A-04 | Gas flow | 0.6011 | 0.4911 | -18.30% | falls | falls | Shares the restricted path, so higher backpressure reduces its drawdown. |
| A-04 | Wellhead pressure | 1,924,944 | 2,256,789 | +17.24% | rises | rises | Backpressure from its header rises. |
| A-05 | Gas flow | 0.5483 | 0.4232 | -22.82% | falls | falls | Shares the restricted path, so higher backpressure reduces its drawdown. |
| A-05 | Wellhead pressure | 1,923,839 | 2,254,929 | +17.21% | rises | rises | Backpressure from its header rises. |
| A-06 | Gas flow | 0.6152 | 0.5181 | -15.79% | falls | falls | Shares the restricted path, so higher backpressure reduces its drawdown. |
| A-06 | Wellhead pressure | 1,931,483 | 2,261,498 | +17.09% | rises | rises | Backpressure from its header rises. |
| HDR-B | Header pressure | 1,911,850 | 1,897,003 | -0.78% | falls | falls | Not on the restricted path. It discharges into a lower manifold pressure. |
| GS-B | Flow | 3.5314 | 3.5559 | +0.69% | rises | rises | The lower manifold pressure lets this branch pass more gas. |
| B-01 | Gas flow | 0.5738 | 0.5781 | +0.75% | rises | rises | Not on the restricted path. It gains from the lower manifold pressure. |
| B-01 | Wellhead pressure | 1,934,898 | 1,920,578 | -0.74% | falls | falls | Its header pressure fell with the manifold. |
| B-02 | Gas flow | 0.5974 | 0.6009 | +0.59% | rises | rises | Not on the restricted path. It gains from the lower manifold pressure. |
| B-02 | Wellhead pressure | 1,934,511 | 1,920,109 | -0.74% | falls | falls | Its header pressure fell with the manifold. |
| B-03 | Gas flow | 0.5573 | 0.5620 | +0.84% | rises | rises | Not on the restricted path. It gains from the lower manifold pressure. |
| B-03 | Wellhead pressure | 1,929,572 | 1,915,162 | -0.75% | falls | falls | Its header pressure fell with the manifold. |
| B-04 | Gas flow | 0.6051 | 0.6092 | +0.68% | rises | rises | Not on the restricted path. It gains from the lower manifold pressure. |
| B-04 | Wellhead pressure | 1,933,910 | 1,919,535 | -0.74% | falls | falls | Its header pressure fell with the manifold. |
| B-05 | Gas flow | 0.6183 | 0.6216 | +0.54% | rises | rises | Not on the restricted path. It gains from the lower manifold pressure. |
| B-05 | Wellhead pressure | 1,937,968 | 1,923,608 | -0.74% | falls | falls | Its header pressure fell with the manifold. |
| B-06 | Gas flow | 0.5796 | 0.5840 | +0.77% | rises | rises | Not on the restricted path. It gains from the lower manifold pressure. |
| B-06 | Wellhead pressure | 1,936,991 | 1,922,726 | -0.74% | falls | falls | Its header pressure fell with the manifold. |
| C-01 | Unit flow | 1.7795 | 1.6251 | -8.68% | falls | falls | Total arrivals fell, and units share flow by available capacity. |
| C-02 | Unit flow | 1.7795 | 1.6251 | -8.68% | falls | falls | Total arrivals fell, and units share flow by available capacity. |
| C-03 | Unit flow | 1.7795 | 1.6251 | -8.68% | falls | falls | Total arrivals fell, and units share flow by available capacity. |
| C-04 | Unit flow | 1.7795 | 1.6251 | -8.68% | falls | falls | Total arrivals fell, and units share flow by available capacity. |

## C-01 capacity falls to 30%

`AETHER-NET-COMPRESSOR-DERATE` against `AETHER-NET-NORMAL`, at day 7.00. Flows in sm3/s, and pressures in Pa absolute.

| Asset | Quantity | Baseline | Faulted | Change | Expected | Observed | Why |
|---|---|---:|---:|---:|---|---|---|
| COMP-SUCTION | Suction pressure | 1,600,000 | 1,628,633 | +1.79% | rises | rises | Arrivals exceed capacity at setpoint, so suction floats up until flow and capacity agree. |
| MANIFOLD | Manifold pressure | 1,720,183 | 1,744,799 | +1.43% | rises | rises | Higher suction raises the pressure the trunk discharges into. |
| C-01 | Unit flow | 1.7795 | 0.6413 | -63.96% | falls | falls | This unit lost capacity. |
| C-02 | Unit flow | 1.7795 | 2.1376 | +20.12% | rises | rises | Takes a larger share as C-01 loses capacity, within its own limit. |
| C-03 | Unit flow | 1.7795 | 2.1376 | +20.12% | rises | rises | Takes a larger share as C-01 loses capacity, within its own limit. |
| C-04 | Unit flow | 1.7795 | 2.1376 | +20.12% | rises | rises | Takes a larger share as C-01 loses capacity, within its own limit. |
| A-01 | Gas flow | 0.6117 | 0.6066 | -0.84% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| A-01 | Wellhead pressure | 1,929,348 | 1,947,833 | +0.96% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| A-02 | Gas flow | 0.5688 | 0.5630 | -1.03% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| A-02 | Wellhead pressure | 1,923,783 | 1,942,340 | +0.96% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| A-03 | Gas flow | 0.6415 | 0.6368 | -0.73% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| A-03 | Wellhead pressure | 1,926,544 | 1,945,149 | +0.97% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| A-04 | Gas flow | 0.6011 | 0.5955 | -0.93% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| A-04 | Wellhead pressure | 1,924,944 | 1,943,508 | +0.96% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| A-05 | Gas flow | 0.5483 | 0.5421 | -1.15% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| A-05 | Wellhead pressure | 1,923,839 | 1,942,347 | +0.96% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| A-06 | Gas flow | 0.6152 | 0.6103 | -0.80% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| A-06 | Wellhead pressure | 1,931,483 | 1,949,933 | +0.96% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| B-01 | Gas flow | 0.5738 | 0.5682 | -0.97% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| B-01 | Wellhead pressure | 1,934,898 | 1,953,204 | +0.95% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| B-02 | Gas flow | 0.5974 | 0.5928 | -0.77% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| B-02 | Wellhead pressure | 1,934,511 | 1,952,918 | +0.95% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| B-03 | Gas flow | 0.5573 | 0.5513 | -1.08% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| B-03 | Wellhead pressure | 1,929,572 | 1,947,991 | +0.95% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| B-04 | Gas flow | 0.6051 | 0.5998 | -0.88% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| B-04 | Wellhead pressure | 1,933,910 | 1,952,283 | +0.95% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| B-05 | Gas flow | 0.6183 | 0.6139 | -0.70% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| B-05 | Wellhead pressure | 1,937,968 | 1,956,323 | +0.95% | rises | rises | Backpressure rises through the shared trunk and manifold. |
| B-06 | Gas flow | 0.5796 | 0.5738 | -0.99% | falls | falls | Higher pressure anywhere on the shared path reduces every well's drawdown. |
| B-06 | Wellhead pressure | 1,936,991 | 1,955,227 | +0.94% | rises | rises | Backpressure rises through the shared trunk and manifold. |

## IV-B closed, C-04 stopped

`AETHER-NET-PLANNED-SHUTDOWN` against `AETHER-NET-NORMAL`, at day 3.25. Flows in sm3/s, and pressures in Pa absolute.

| Asset | Quantity | Baseline | Faulted | Change | Expected | Observed | Why |
|---|---|---:|---:|---:|---|---|---|
| GS-B | Flow | 3.5314 | 0.0000 | -100.00% | falls | falls | Its isolation valve is closed. |
| MANIFOLD | Manifold pressure | 1,720,183 | 1,633,287 | -5.05% | falls | falls | The shared trunk carries about half the gas, so its friction loss falls. |
| COMP-SUCTION | Suction pressure | 1,600,000 | 1,600,000 | +0.00% | unchanged | unchanged | Arrivals fell by more than the stopped unit's capacity, so setpoint still holds. |
| C-04 | Unit flow | 1.7795 | 0.0000 | -100.00% | falls | falls | This unit is stopped. |
| B-01 | Gas flow | 0.5738 | 0.0000 | -100.00% | falls | falls | Its outlet path is closed. |
| B-02 | Gas flow | 0.5974 | 0.0000 | -100.00% | falls | falls | Its outlet path is closed. |
| B-03 | Gas flow | 0.5573 | 0.0000 | -100.00% | falls | falls | Its outlet path is closed. |
| B-04 | Gas flow | 0.6051 | 0.0000 | -100.00% | falls | falls | Its outlet path is closed. |
| B-05 | Gas flow | 0.6183 | 0.0000 | -100.00% | falls | falls | Its outlet path is closed. |
| B-06 | Gas flow | 0.5796 | 0.0000 | -100.00% | falls | falls | Its outlet path is closed. |
| A-01 | Gas flow | 0.6117 | 0.6292 | +2.85% | rises | rises | It discharges into a lower manifold pressure while the other pad is out. |
| A-02 | Gas flow | 0.5688 | 0.5886 | +3.48% | rises | rises | It discharges into a lower manifold pressure while the other pad is out. |
| A-03 | Gas flow | 0.6415 | 0.6575 | +2.50% | rises | rises | It discharges into a lower manifold pressure while the other pad is out. |
| A-04 | Gas flow | 0.6011 | 0.6199 | +3.14% | rises | rises | It discharges into a lower manifold pressure while the other pad is out. |
| A-05 | Gas flow | 0.5483 | 0.5696 | +3.88% | rises | rises | It discharges into a lower manifold pressure while the other pad is out. |
| A-06 | Gas flow | 0.6152 | 0.6320 | +2.72% | rises | rises | It discharges into a lower manifold pressure while the other pad is out. |
