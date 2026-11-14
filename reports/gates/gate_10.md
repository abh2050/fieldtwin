# Gate 10 report: portfolio demonstration

**Status: implemented and stopped for technical review.** The work is on branch `gate-10`, stacked on `gate-8` (PR #13), and isn't merged.

Date: 2026-11-14. Branch: `gate-10`. Logs:

- Evidence run: [`gate_10_execution_log.txt`](gate_10_execution_log.txt).
- Clean-checkout demo: [`gate_10_clean_copy_log.txt`](gate_10_clean_copy_log.txt), with tokens redacted and progress lines dropped.

Scope change: [ADR 0022](../../docs/adr/0022-no-cloud-deployment.md) removes Gate 9 (AWS) at the owner's request.

> AETHER Field is fictional. Nothing in this gate adds a new result. It packages, checks, and presents the results of Gates 0 to 8 and D1.

## Headline

- **One command takes a clean checkout to the running app, and that was proven, not assumed.**
  - `scripts/clean_copy_demo.sh` copied only the 525 tracked files (no data, model, database, or `node_modules`) and ran `scripts/run_demo.sh`.
  - It downloaded the four public sources, rebuilt the database and field, and retrained the Gate 5 detector.
  - It built the aerial evidence and decisions, then served the app. That took 64 minutes.
  - The live smoke test then passed all 28 reads and the 13-step workflow.
- **The detector retrained from nothing reproduced Gate 5 exactly.** Every recorded value matched, including 57 checksums, and the model artifact's SHA-256 (`2fca62fa…`) equalled the committed one.
- **The test found three hidden steps or defects, each fixed before it passed.**
  1. A fresh OCD release needs `make profile` before validation.
  2. The selected model is written by the held-out stage, not the in-regime one.
  3. The reproduction check compared whole files, which can't match because they record the commit and timings.

  A fourth failed run was a transient "network unreachable" during the NAIP search. It passed on retry, with nothing changed.
- **No cloud and no paid API.** The measured spend is $0.
  - CI: 103 workflow runs and 901 jobs, 560.5 job-minutes, free for a public repository.
  - One AI illustration, which used 0.15 of the owner's 10 free Higgsfield credits (balance 9.85 afterwards), discussed below.

## Acceptance

The specification's Gate 10 deliverables, and the section 23 criteria that were partial or not started at Gate 8.

| # | Deliverable or criterion | Result | Evidence |
|---:|---|---|---|
| 1 | Architecture diagrams | **Met** | `docs/architecture.drawio`: new "System architecture" and "Local runtime and trust boundaries" pages replace the initial logical page and the proposed AWS page. The eight gate pages are kept. The project page has a data-flow diagram. |
| 2 | Reproducible walkthrough | **Met** | [Walkthrough](../../docs/demos/walkthrough.md), `scripts/run_demo.sh`, and the clean-copy proof above |
| 3 | Technical documentation | **Met** | [Technical overview](../../docs/technical_overview.md), app READMEs, and 22 ADRs |
| 4 | Model evaluation | **Met** | [Evaluation summary](../portfolio/evaluation_summary.md), generated from the committed result files with their hashes. A test regenerates it and fails on drift. |
| 5 | Cost measurements | **Met, local** | [Costs and teardown](../portfolio/costs.md): dependency scan for paid SDKs, every CI run from the GitHub API, rebuild durations, and disk. There are no cloud costs, by ADR 0022. |
| 6 | Security review | **Met** | [Security review](../../docs/security_review.md): threat model, controls with evidence, Bandit triage, and two new tests (SQL injection through filters, and path traversal in the served web build). One low finding fixed. |
| 7 | Known limitations | **Met** | [Known limitations](../../docs/limitations.md) |
| 8 | Demo video script | **Met** | [Video script](../../docs/demos/video_script.md), about 4 minutes. It warns not to film screens that show real well identifiers. |
| 9 | Production-hardening roadmap | **Met** | [Roadmap](../../docs/roadmap.md). It starts with earning the capability, since the evidence says detection doesn't yet pay. |
| 10 | `docs/index.html` functions | **Met** | Rebuilt as the project page. A test checks that every local link resolves, that it names no OCD well, and that each evidence figure appears in the generated summary. It was checked at desktop width and in a 390-pixel phone frame. |
| 11 | Demo reproducible without hidden manual steps | **Met** | Clean-copy run, above |
| 12 | Local deployment validated (replaces the AWS criterion, ADR 0022) | **Met** | Clean-copy run and live smoke test |
| 13 | Costs and teardown documented (replaces the AWS criterion) | **Met** | [Costs and teardown](../portfolio/costs.md) |
| 14 | Tests and CI | **Met** | 685 offline, 270 database, and 17 web tests. Every CI command in a clean copy. Hosted CI on PR #14 (commit `17c6301`): all 10 jobs passed on both the push and pull-request runs. |

## What the clean-copy rebuild changed

The rebuild rewrote six tracked files. The script's final check failed on them, because it then failed on any change. Each was classified by hand:

| File | Why it changed | A result? |
|---|---|---|
| `reports/data_quality/nm_ocd.json`, `.md` | OCD published a newer release after 2026-11-05, so the copy downloaded and profiled a new batch | No: a profile of new upstream data |
| `data/manifests/petrobras_3w/…json` | Same version (2.0.0) downloaded again, so a new ingestion timestamp | No |
| `reports/gates/gate_1_validation.json`, `gate_6_validation.json` | Validation time and batch IDs | No |
| `reports/experiments/results/aether_dataset.json` | Generation timings only. Its dataset and parameter checksums are among the 57 verified values. | No |
| `reports/experiments/attempts/attempts.jsonl` | The two Gate 5 stage reruns, appended as the ledger requires | No |

The check now fails only when a recorded result changes. That covers the experiment results, decision, inspection, and diagnostics files. It still lists every other change. It was corrected after this run and hasn't been rerun, because a rerun downloads 1.7 GB.

## Scope and other decisions to review

- **Gate 9 is removed, not deferred** (ADR 0022). The `aws-*` targets, scripts, the `infra/` folder, the AWS cost plan, and the AWS settings in `.env.example` are deleted. ADRs 0001 and 0002 are marked superseded.
- **Unfilled scaffold folders were removed.** Their READMEs promised work that was never done or is now out of scope: `pipelines/publish`, `packages/telemetry`, `packages/provenance`, `models/`, `config/environments`, `tests/{e2e,security,performance}`, `data_contracts/canonical`, and `reports/aws`.
- **The demo serves the built web app from the API** (`FIELDTWIN_WEB_DIST`), so it needs one process and one URL. Files are served only from inside the build folder, which a test checks.
- **The Gate 5 rebuild in the demo restores the committed results files** after verifying them, so running the demo never rewrites recorded results.
- **AI-generated imagery.** At the owner's request, the project page's hero background is an AI illustration made with Higgsfield (Z Image, free plan). It is captioned on the page as AI-generated, "not a real site, and not AETHER data". Every image of the app on the page is a real screenshot. Two credentials pasted into the conversation were not used or stored; the already-connected integration was used instead.
- **The page shows only screens without real well identifiers** (AGENTS.md rule 10): Overview, Telemetry Lab, Decision Center, Maintenance, and Experiment Reports. A test checks the page text for OCD API numbers. It can't read images, so the screen selection was made by hand.

## Not done

- No browser end-to-end test runs in CI, and MapLibre's WebGL drawing wasn't checked automatically; both are listed in the limitations.
- No demo video was recorded; only its script exists.
