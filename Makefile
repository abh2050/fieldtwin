.PHONY: gate5-audit gate5-data gate5-development gate5-holdout gate5-performance gate5-stress gate5-reports gate5 field field-reports gate4 scenario reconcile benchmark-events gate3-reports gate3 gate2-reports schema-docs db-up db-down db-reset db-migrate db-seed db-load schemas typecheck test-db test-contract gate2 bootstrap test lint validate acquire acquire-ocd acquire-3w profile fixtures aws-plan aws-deploy aws-smoke-test aws-stop aws-destroy

bootstrap:
	bash scripts/bootstrap.sh

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy

# Local PostGIS on port 55432.
db-up:
	docker compose up -d --wait postgres

db-down:
	docker compose down

# Deletes only this project's local database volume.
db-reset:
	docker compose down -v
	docker compose up -d --wait postgres

db-migrate:
	uv run python -m packages.repositories.database

db-seed:
	uv run python -m pipelines.normalize.seed

db-load:
	uv run python -m pipelines.normalize.load

# AETHER-FAULT-001: synthetic telemetry, invariants, events, and lineage.
scenario:
	uv run python -m pipelines.synthetic.aether_fault_001

benchmark-events:
	uv run python -m pipelines.normalize.petrobras_3w_events

reconcile:
	uv run python -m pipelines.reconcile.run

gate3-reports:
	uv run python -m pipelines.reconcile.reports
	uv run python -m pipelines.synthetic.report

# Gate 5. Development stages choose a method; holdout stages read the holdout once.
gate5-audit:
	uv run python -m pipelines.experiments.three_w_audit

gate5-data:
	uv run python -m pipelines.experiments.aether_data

gate5-development:
	uv run python -m pipelines.experiments.three_w_run --stage development
	uv run python -m pipelines.experiments.aether_run --stage in_regime

gate5-holdout:
	uv run python -m pipelines.experiments.three_w_run --stage holdout
	uv run python -m pipelines.experiments.aether_run --stage held_out

gate5-performance:
	uv run python -m pipelines.experiments.inference_perf

gate5-stress:
	uv run python -m pipelines.experiments.reliability_stress

gate5-reports:
	uv run python -m pipelines.experiments.reports

gate5:
	bash scripts/gate5_evidence.sh

# The whole fictional field: six scenarios, checks, outputs, and lineage.
field:
	uv run python -m pipelines.synthetic.aether_field

field-reports:
	uv run python -m pipelines.synthetic.field_reports

gate4:
	bash scripts/gate4_evidence.sh

gate3:
	bash scripts/gate3_evidence.sh

gate2-reports:
	uv run python -m pipelines.normalize.reports

schema-docs:
	uv run python -m pipelines.normalize.schema_docs

schemas:
	uv run python -m pipelines.profile.source_schemas

test-db:
	uv run pytest -m "db and not acquired" -o addopts=""

gate2:
	bash scripts/gate2_evidence.sh

# Real downloads, about 1.6 GB. Reuses a completed batch unless REFRESH=1.
acquire: acquire-ocd acquire-3w

acquire-ocd:
	uv run python -m pipelines.acquire.cli nm_ocd $(if $(REFRESH),--refresh)

acquire-3w:
	uv run python -m pipelines.acquire.cli petrobras_3w $(if $(REFRESH),--refresh)

profile:
	uv run python -m pipelines.profile.cli

# Re-cut offline test fixtures from acquired data.
fixtures:
	uv run python -m scripts.cut_fixtures

validate:
	bash scripts/validate.sh

# AWS targets are placeholders until Gate 9. They fail on purpose and create nothing.
aws-plan:
	bash scripts/aws_plan.sh

aws-destroy:
	bash scripts/aws_destroy.sh

aws-deploy aws-smoke-test aws-stop:
	@echo "$@ is not implemented until Gate 9. Nothing was done." >&2; exit 2
