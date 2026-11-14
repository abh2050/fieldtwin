"""The API against a real migrated database, through the `fieldtwin_app` role.

A throwaway database is migrated, seeded from the committed CI fixtures, and given the six recorded
field runs (their output files written to a temporary root), one test alarm, and two recommendations.
The API commits its own transactions, so the database is dropped afterwards.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from fieldtwin_api.db import _connect
from fieldtwin_api.main import create_app
from fieldtwin_api.routers.scenarios import SERIES_COLUMNS
from fieldtwin_api.settings import Settings, parse_tokens

from packages.repositories.database import REPO_ROOT, database_url, migrate

pytestmark = pytest.mark.db
RUN = "AETHER-FAULT-001-NET:v1:fault"
SCENARIO = "AETHER-FAULT-001-NET"
T0 = datetime(2040, 1, 4, 12, tzinfo=UTC)
TERMS = [{"name": "alarm_started", "points": 30, "input": "1", "rule": "r"}]
SUP, OP, VIEW = (
    "sup-token-0123456789abcdef",
    "op-token-0123456789abcdefgh",
    "view-token-0123456789abcdef",
)


def _url(name: str) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    return make_conninfo(**{**conninfo_to_dict(database_url()), "dbname": name})


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("api_root")
    shutil.copytree(
        REPO_ROOT / "reports", path / "reports"
    )  # committed results; data/gold is left unbuilt
    return path


@pytest.fixture(scope="module")
def database(root):
    from pipelines.normalize.load import load_all
    from pipelines.normalize.seed import seed
    from pipelines.reconcile.run import load_rules
    from pipelines.synthetic.aether_field import execute_all, persist_all, write_outputs

    name = f"ft_api_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(database_url(), autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    url = _url(name)
    try:
        with psycopg.connect(url) as conn:
            migrate(conn)
            seed(conn)
            load_all(conn, REPO_ROOT / "data" / "fixtures" / "ci_workspace")
            results = execute_all()
            persist_all(
                conn, results, write_outputs(root, results), load_rules()["algorithms"]["scenario"]
            )
            conn.execute(
                """INSERT INTO detector_alarms (alarm_id, scenario_id, scenario_run_id, started_at, score, threshold,
                     model_id, model_version, model_sha256, evidence, earlier_starts_in_lookback, first_alarm_at,
                     provenance_class, input_provenance)
                   VALUES ('ALM-T', %s, %s, %s, 2.0, 1.5, 'm', '1', %s, '[]', 0, %s, 'INFERRED', 'SYNTHETIC')""",
                (SCENARIO, RUN, T0, "0" * 64, T0),
            )
            for rec_id, action, candidates, band in (
                ("REC-DISPATCH", "FIELD_INSPECTION", ["GS-A", "A-02"], "P2"),
                ("REC-QUIET", "NO_ACTION_PLANNED_OPERATION", [], None),
            ):
                conn.execute(
                    """INSERT INTO recommendations (recommendation_id, alarm_id, scenario_id, scenario_run_id, decided_at,
                         action, candidate_assets, suppressed_assets, priority_score, priority_band, respond_within_h,
                         terms, explanation, rules_version, provenance_class)
                       VALUES (%s, 'ALM-T', %s, %s, %s, %s, %s, '{}', 30, %s, %s, %s, '["why"]', 3, 'SYNTHETIC')""",
                    (
                        rec_id,
                        SCENARIO,
                        RUN,
                        T0,
                        action,
                        candidates,
                        band,
                        72 if band else None,
                        json.dumps(TERMS),
                    ),
                )
        yield url
    finally:
        with psycopg.connect(database_url(), autocommit=True) as admin:
            admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture(scope="module")
def client(database, root) -> TestClient:
    tokens = parse_tokens(f"sup:MAINTENANCE_SUPERVISOR:{SUP},op:OPERATOR:{OP},view:VIEWER:{VIEW}")
    return TestClient(create_app(Settings(database_url=database, repo_root=root, tokens=tokens)))


def auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def test_health_uses_the_application_role(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["checks"]["role"] == "fieldtwin_app"
    assert body["checks"]["latest_migration"] == "0016_application_state.sql"


def test_the_application_role_cannot_write_engine_or_source_tables(database, root):
    conn = _connect(Settings(database_url=database, repo_root=root), read_only=False)
    try:
        for sql in (
            "INSERT INTO detector_alarms (alarm_id) VALUES ('X')",
            "UPDATE recommendations SET priority_score = 0",
            "DELETE FROM audit_events",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(sql)
            conn.rollback()
            conn.execute("SET ROLE fieldtwin_app")
    finally:
        conn.close()


def test_reads_are_paginated_with_a_total(client):
    first = client.get("/api/v1/assets", params={"limit": 5}).json()
    second = client.get("/api/v1/assets", params={"limit": 5, "offset": 5}).json()
    assert first["total"] == second["total"] > 5
    assert {a["asset_id"] for a in first["items"]}.isdisjoint(
        a["asset_id"] for a in second["items"]
    )
    assert all(a["is_fictional"] for a in first["items"])


def test_filters_and_validation(client):
    wells = client.get("/api/v1/assets", params={"asset_type": "WELL", "limit": 500}).json()
    assert wells["total"] == 12 and all(a["asset_type"] == "WELL" for a in wells["items"])
    bad = client.get("/api/v1/assets", params={"limit": 0})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_FAILED"


def test_asset_detail_relationships_and_missing_asset(client):
    assert client.get("/api/v1/assets/A-01").json()["sensors"]
    assert client.get("/api/v1/assets/GS-A/relationships").json()["physical"]
    missing = client.get("/api/v1/assets/NOPE")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "ASSET_NOT_FOUND"


def test_network_is_local_schematic_coordinates(client):
    body = client.get("/api/v1/network").json()
    assert body["coordinate_system"] == "LOCAL_METRES"
    assert len(body["nodes"]) > 10 and len(body["edges"]) > 10


def test_telemetry_is_the_stored_series_without_simulator_truth(client):
    path = f"/api/v1/scenarios/{SCENARIO}/runs/{RUN}/telemetry"
    full = client.get(path, params={"tag": "A-01.PT-WH"}).json()
    assert len(full["points"]) == 2016
    assert set(full["points"][0]) == set(SERIES_COLUMNS)
    assert full["provenance_class"] == "SYNTHETIC"
    cut = client.get(path, params={"tag": "A-01.PT-WH", "until_offset_s": 3600}).json()
    assert [p["offset_s"] for p in cut["points"]] == list(range(0, 3601, 300))
    assert client.get(path, params={"tag": "NOPE"}).status_code == 404


def test_telemetry_refuses_a_file_that_does_not_match_its_run(client, root):
    import pandas as pd

    path = root / "data/gold/scenarios/aether_field/AETHER-NET-NORMAL_telemetry.parquet"
    frame = pd.read_parquet(path)
    frame.iloc[:-1].to_parquet(path, index=False)  # one row missing
    response = client.get(
        "/api/v1/scenarios/AETHER-NET-NORMAL/runs/AETHER-NET-NORMAL:v1:nominal/telemetry",
        params={"tag": frame["tag"].iloc[-1]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OUTPUT_DOES_NOT_MATCH_RUN"


def test_unbuilt_results_are_reported_not_replaced(client):
    response = client.get("/api/v1/inspections")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "RESULT_NOT_BUILT" and error["details"]["build_with"] == "make gate6"


def test_committed_results_are_served_with_their_hash(client):
    d1 = client.get("/api/v1/diagnostics/d1").json()
    assert d1["outcome"]["outcome"] == "NOT_MET"
    assert all(len(s["sha256"]) == 64 for s in d1["sources"])
    economics = client.get("/api/v1/economics/comparison").json()
    assert "Not realized" in economics["label"]
    assert set(economics["policies"]) == {"FIXED", "RISK_BASED", "ROUTE_OPTIMIZED"}
    evaluations = client.get("/api/v1/model-evaluations").json()
    assert evaluations["selected_method"] == "hist_gradient_boosting"
    assert len(evaluations["reproducibility"]["git_sha"]) == 40
    overview = client.get("/api/v1/overview").json()
    assert overview["d1_outcome"] == "NOT_MET"
    assert overview["detection"]["events"] > overview["detection"]["events_detected"] > 0
    report = client.get("/api/v1/reports/d1").json()
    assert report["markdown"].startswith("# D1 final result")


def test_lineage_of_a_synthetic_observation(client, database):
    with psycopg.connect(database) as conn:
        observation_id = conn.execute(
            "SELECT observation_id FROM observations WHERE scenario_run_id = %s LIMIT 1", (RUN,)
        ).fetchone()[0]
    body = client.get(f"/api/v1/lineage/observation:{observation_id}").json()
    assert body["lineage"]["synthetic_chain"]["chain_complete"] is True
    assert client.get("/api/v1/lineage/observation:999999999").status_code == 404
    assert client.get("/api/v1/lineage/nonsense").status_code == 422


def test_work_order_lifecycle_through_the_guarded_path(client, database):
    body = {"recommendation_id": "REC-DISPATCH"}
    assert client.post("/api/v1/work-orders", json=body).status_code == 401
    assert client.post("/api/v1/work-orders", json=body, headers=auth(VIEW)).status_code == 403

    created = client.post("/api/v1/work-orders", json=body, headers=auth(OP, "create-key-0001"))
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "RECOMMENDED" and order["asset_id"] == "GS-A"
    assert order["transitions"][0]["actor_kind"] == "SYSTEM"
    assert "at the request of op" in order["transitions"][0]["justification"]

    # The same key and body returns the first response and creates nothing new.
    again = client.post("/api/v1/work-orders", json=body, headers=auth(OP, "create-key-0001"))
    assert again.status_code == 201 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == order
    reused = client.post(
        "/api/v1/work-orders",
        json={"recommendation_id": "REC-QUIET"},
        headers=auth(OP, "create-key-0001"),
    )
    assert reused.status_code == 422 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    duplicate = client.post("/api/v1/work-orders", json=body, headers=auth(OP))
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "WORK_ORDER_EXISTS"
    quiet = client.post(
        "/api/v1/work-orders", json={"recommendation_id": "REC-QUIET"}, headers=auth(OP)
    )
    assert (
        quiet.status_code == 409
        and quiet.json()["error"]["code"] == "RECOMMENDATION_DOES_NOT_DISPATCH"
    )

    wo = order["work_order_id"]
    decision = {"justification": "Evidence reviewed in the app."}
    assert (
        client.post(
            f"/api/v1/work-orders/{wo}/approve", json=decision, headers=auth(OP)
        ).status_code
        == 403
    )
    blank = client.post(
        f"/api/v1/work-orders/{wo}/approve", json={"justification": "   "}, headers=auth(SUP)
    )
    assert blank.status_code == 422

    approved = client.post(
        f"/api/v1/work-orders/{wo}/approve", json=decision, headers=auth(SUP, "approve-key-01")
    )
    assert approved.status_code == 200, approved.text
    last = approved.json()["transitions"][-1]
    assert approved.json()["status"] == "APPROVED"
    assert (last["actor_id"], last["actor_kind"], last["actor_role"]) == (
        "sup",
        "HUMAN",
        "MAINTENANCE_SUPERVISOR",
    )
    assert approved.json()["decided_by_kinds"] == ["HUMAN"]

    replayed = client.post(
        f"/api/v1/work-orders/{wo}/approve", json=decision, headers=auth(SUP, "approve-key-01")
    )
    assert replayed.status_code == 200 and replayed.headers["Idempotent-Replayed"] == "true"
    twice = client.post(f"/api/v1/work-orders/{wo}/approve", json=decision, headers=auth(SUP))
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "INVALID_TRANSITION"
    assert (
        client.post(
            f"/api/v1/work-orders/{wo}/reject", json=decision, headers=auth(SUP)
        ).status_code
        == 409
    )
    done = client.post(
        f"/api/v1/work-orders/{wo}/complete",
        json={"justification": "Visit simulated."},
        headers=auth(OP),
    )
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
    assert (
        client.post(
            "/api/v1/work-orders/WO-none/approve", json=decision, headers=auth(SUP)
        ).status_code
        == 404
    )

    with psycopg.connect(database) as conn:
        rows = conn.execute(
            """SELECT t.decision, t.actor_kind, (SELECT count(*) FROM audit_events e
                 WHERE e.correlation_id = 'transition:' || t.transition_id) FROM work_order_transitions t
                 JOIN work_orders w USING (work_order_id) WHERE w.external_id = %s ORDER BY t.sequence""",
            (wo,),
        ).fetchall()
        approvals = conn.execute(
            "SELECT actor_kind FROM approval_events a JOIN work_orders w USING (work_order_id) WHERE w.external_id = %s",
            (wo,),
        ).fetchall()
    assert rows == [("CREATE", "SYSTEM", 1), ("APPROVE", "HUMAN", 1), ("COMPLETE", "HUMAN", 1)]
    assert approvals == [("HUMAN",)]
    audit = client.get("/api/v1/audit-events", params={"target_id": wo}).json()["items"]
    assert {e["actor_id"] for e in audit} == {"op", "sup"}


def test_replay_moves_a_cursor_and_is_audited(client):
    base = f"/api/v1/scenarios/{SCENARIO}"
    assert client.post(f"{base}/replay").status_code == 401
    assert client.post(f"{base}/reset", headers=auth(OP)).status_code == 409  # nothing to reset yet
    started = client.post(f"{base}/replay", json={"speed": 60}, headers=auth(OP)).json()["replay"]
    assert started["state"] == "PLAYING" and started["scenario_run_id"] == RUN
    assert (
        client.post(f"{base}/replay", headers=auth(OP)).json()["error"]["code"] == "ALREADY_PLAYING"
    )
    paused = client.post(f"{base}/pause", headers=auth(OP)).json()["replay"]
    assert paused["state"] == "PAUSED"
    assert client.post(f"{base}/pause", headers=auth(OP)).status_code == 409
    reset = client.post(f"{base}/reset", headers=auth(SUP)).json()["replay"]
    assert (reset["state"], reset["position_s"]) == ("STOPPED", 0)
    listed = {s["scenario_id"]: s for s in client.get("/api/v1/scenarios").json()["items"]}
    assert listed[SCENARIO]["replay"]["state"] == "STOPPED"
    ops = [
        e["operation"]
        for e in client.get("/api/v1/audit-events", params={"target_id": RUN}).json()["items"]
    ]
    assert ops == ["SCENARIO_RESET", "SCENARIO_PAUSE", "SCENARIO_REPLAY"]
    assert client.post("/api/v1/scenarios/NOPE/replay", headers=auth(OP)).status_code == 404
    other_run = client.post(
        f"{base}/replay", json={"scenario_run_id": "AETHER-NET-NORMAL:v1:nominal"}, headers=auth(OP)
    )
    assert other_run.status_code == 404
