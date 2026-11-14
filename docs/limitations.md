# Known limitations

FieldTwin is an engineering demonstration on a fictional facility. This page lists what it does not show, so that nothing in the repository is read as a stronger claim than its evidence supports. Numbers are in the [evaluation summary](../reports/portfolio/evaluation_summary.md).

## What the results don't establish

- **Nothing is field-validated.** AETHER Field is fictional, and its physics model is uncalibrated. Every synthetic result describes that model, not a real gathering system.
- **Detection is weak.**
  - On the synthetic track, the selected detector caught under half of held-out events.
  - On real Petrobras 3W wells, the method selected in development caught 1 of 40 holdout events. The one method whose skill interval excluded zero there wasn't the selected one, and its interval is wide.
  - 3W is offshore oil-well data. Several of its event classes have no counterpart in an onshore gas field.
- **Alarm-driven maintenance lost in the model.** Fixed monthly rounds had the lowest mean modeled cost. The economics are model estimates under declared assumptions, not savings.
- **D1, model-based diagnosis, was NOT MET.** It is near-perfect only inside the model it inverts, an "inverse crime". It fails with missing telemetry and a compressor outside its trained range, and its intervals are too narrow at high severity.
- **Aerial evidence is proximity only.** Plumes sit nearer registered wells than a footprint-matched null predicts, but no plume is attributed to a source. No person has reviewed the image chips yet.
- **Reproduction is shown on one machine.** Simulator hashes are checked on three platforms in CI. Model scores were reproduced only on the development machine.
- **The Gate 5 and Gate 7 rules changed after some results were seen.** Each change is disclosed in its report. D1 alone was fully preregistered and scored once.

## What the application doesn't do

- **It is local only** (ADR 0022). There's no hosting, TLS, managed identity, token expiry, or rate limiting.
- **Technician assignment isn't modeled.** Work orders have no crew field.
- **Blind review of aerial chips stays in the command line** (`make inspection-review`), so the reviewer never sees plume status.
- **Gate 3 single-segment runs aren't served** in the Telemetry Lab, because their files mix readings with truth.
- **MapLibre's WebGL drawing wasn't checked by an automated test.** Headless Chrome on the build machine couldn't draw it. An SVG fallback is used and was checked. No browser end-to-end test runs in CI.
- **A decision made in the app defaults to the scenario-clock time of the latest transition.** Real time is recorded separately.

## Data

- **NM OCD:** the data comes from an unauthenticated FTP server with no publisher checksum and no stated licence. Raw rows aren't committed, and well locations are approximate.
- **NAIP:** licensing for 2022 imagery is listed as not confirmed. Image chips are used as context only.
- **Carbon Mapper:** non-commercial research and demonstration use only.
- **Data refresh:** the public sources change. A fresh `run_demo.sh` downloads the current releases, so its counts can differ from those recorded in the gate reports, which name their batch IDs.
