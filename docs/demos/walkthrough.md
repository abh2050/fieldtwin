# Reproducible walkthrough

From a clean checkout to an approved simulated work order, with nothing done by hand except the clicks in the app. Every step is a command in this repository.

## 0. Requirements

- macOS or Linux, with about 6 GB free disk.
- [uv](https://docs.astral.sh/uv/), Node 20 or later with npm, and Docker (running).
- Network access for the first run. It downloads the four public sources, about 1.7 GB, and later runs reuse completed batches. No account, key, or paid service is needed.

## 1. Build and start

```bash
git clone https://github.com/abh2050/fieldtwin.git && cd fieldtwin
bash scripts/run_demo.sh
```

The script:

1. Installs the Python and web dependencies.
2. Acquires and validates the public sources.
3. Builds a fresh local database and the six simulated field scenarios.
4. Retrains the Gate 5 detector if needed. It refuses to continue unless the model's checksum matches the committed results.
5. Builds the aerial evidence and the decision engine's recommendations.
6. Loads the demo **without** any work order, so every decision you see was made by a person.
7. Serves everything on **http://127.0.0.1:8000**.

It prints three local sign-in tokens, one each for viewer, operator, and maintenance supervisor. A first run takes tens of minutes, mostly downloading and retraining.

`scripts/clean_copy_demo.sh` proves this works with no hidden step. It runs the same script in a copy holding only the tracked files, then smoke-tests the result. Its last run is recorded in the [Gate 10 report](../../reports/gates/gate_10.md).

## 2. Look around (no sign-in needed)

| Screen | What to notice |
|---|---|
| **Overview** | Counts from the database. The findings card leads with the negative results, each figure read from a committed result file. |
| **Field Map** | The fictional network in local metres, with no real location. Red marks the candidates of dispatching recommendations. |
| **Telemetry Lab** | Pick `AETHER-FAULT-001-NET:v1:fault` and `A-01.FT`. The flow falls as the gathering line restricts, and the red line is the detector's alarm. "Show scenario truth" adds the real fault onset, which the detector never saw. |
| **Aerial Inspection** | Real plumes near real registered wells, labelled as proximity only, kept apart from the fictional field. |
| **Experiment Reports** | D1's preregistered acceptance lines, with the failed one highlighted. The model comparison and full reports are below it. |

## 3. Make a decision

1. Click **Sign in to act** and paste the **operator** token.
2. **Decision Center:** on the GS-A field inspection (score 50, P2), read the explanation and the scoring terms, then click **Open work order**.
3. Sign out, and sign in with the **maintenance supervisor** token.
4. **Maintenance:** select the new work order, write a justification, and click **Approve**.
   - The timeline shows the engine's `SYSTEM` creation and your `HUMAN` approval.
   - Approve is no longer offered. If it were sent anyway, the API and the database would both refuse it; `scripts/gate8_smoke.py` checks exactly that.
5. As operator, click **Record simulated visit complete**.
6. **Telemetry Lab:** as operator, click **Replay** to play the stored run, then **Pause** and **Reset**. Each change is audited.

## 4. Check the evidence behind it

```bash
make test                                  # offline suite
bash scripts/ci_local.sh                   # every CI command in a clean copy (needs PostGIS)
uv run python scripts/portfolio_summary.py # regenerate the evaluation summary; git diff shows nothing
```

## 5. Tear down

```bash
docker compose down -v      # deletes only this project's local database volume
```

[`reports/portfolio/costs.md`](../../reports/portfolio/costs.md) lists everything else that can be removed.
