"""API behaviour that needs no database: authentication order, errors, correlation IDs, replay math.

The database URL points at a closed port, so any request that reached the database would get a 503.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from fieldtwin_api.context import accept_or_new
from fieldtwin_api.idempotency import request_hash
from fieldtwin_api.main import create_app
from fieldtwin_api.routers.scenarios import _replay_view
from fieldtwin_api.settings import Settings, parse_tokens

from packages.repositories.database import REPO_ROOT

SUPERVISOR = "local-supervisor-token-000001"
VIEWER = "local-viewer-token-00000001"
DOWN = "postgresql://nobody:x@127.0.0.1:1/none"


@pytest.fixture
def client() -> TestClient:
    tokens = parse_tokens(f"sup:MAINTENANCE_SUPERVISOR:{SUPERVISOR},view:VIEWER:{VIEWER}")
    return TestClient(create_app(Settings(database_url=DOWN, repo_root=REPO_ROOT, tokens=tokens)))


def test_tokens_are_parsed_and_only_their_hashes_kept():
    tokens = parse_tokens(f"sup:MAINTENANCE_SUPERVISOR:{SUPERVISOR}")
    assert SUPERVISOR not in str(tokens)
    assert next(iter(tokens.values())).role == "MAINTENANCE_SUPERVISOR"


@pytest.mark.parametrize(
    "spec",
    ["sup:ADMIN:" + "x" * 30, "sup:VIEWER:short", "missing-parts", "sup::" + "x" * 30],
)
def test_malformed_token_settings_are_refused(spec):
    with pytest.raises(ValueError):
        parse_tokens(spec)


def test_a_write_without_a_token_is_refused_before_the_database(client):
    response = client.post("/api/v1/work-orders", json={"recommendation_id": "REC-1"})
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "AUTHENTICATION_REQUIRED"
    assert error["correlation_id"] == response.headers["X-Request-ID"]


def test_an_unknown_token_is_refused(client):
    response = client.post(
        "/api/v1/scenarios/S/replay", headers={"Authorization": "Bearer " + "z" * 30}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


def test_a_viewer_cannot_change_state(client):
    for path in (
        "/api/v1/scenarios/S/replay",
        "/api/v1/scenarios/S/pause",
        "/api/v1/scenarios/S/reset",
    ):
        response = client.post(path, headers={"Authorization": f"Bearer {VIEWER}"})
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "FORBIDDEN"
    response = client.post(
        "/api/v1/work-orders/WO-1/approve",
        headers={"Authorization": f"Bearer {VIEWER}"},
        json={"justification": "looks right"},
    )
    assert response.status_code == 403


def test_reads_report_an_unreachable_database_as_unavailable(client):
    response = client.get("/api/v1/assets")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_health_reports_degraded_with_the_disclosure(client):
    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert "fictional" in body["disclosure"]


def test_correlation_ids_are_echoed_when_safe_and_replaced_when_not(client):
    assert (
        client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"]
        == "abc-123"
    )
    replaced = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"}).headers[
        "X-Request-ID"
    ]
    assert replaced != "bad id\nwith newline" and len(replaced) == 36
    assert accept_or_new(None) != accept_or_new(None)


def test_unknown_routes_use_the_error_shape(client):
    response = client.get("/api/v1/nothing-here")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_request_hash_depends_on_method_path_and_body():
    a = request_hash("POST", "/x", {"a": 1, "b": 2})
    assert a == request_hash("POST", "/x", {"b": 2, "a": 1})
    assert a != request_hash("POST", "/y", {"a": 1, "b": 2})
    assert a != request_hash("POST", "/x", {"a": 2, "b": 2})


RUN = {"sample_count": 100, "sampling_interval_s": 60}


def _row(state, position, speed=60.0, seconds_ago=0.0):
    return {
        "scenario_run_id": "S:v1:fault",
        "state": state,
        "position_s": position,
        "speed": speed,
        "anchored_at": datetime.now(UTC) - timedelta(seconds=seconds_ago),
        "updated_by": "op",
    }


def test_a_playing_replay_advances_with_real_time_at_its_speed():
    view = _replay_view(_row("PLAYING", 600, speed=60.0, seconds_ago=10), RUN)
    assert view is not None and view["state"] == "PLAYING"
    assert 1190 <= view["position_s"] <= 1260


def test_a_replay_stops_at_the_end_of_the_stored_run():
    view = _replay_view(_row("PLAYING", 5000, speed=600.0, seconds_ago=100), RUN)
    assert view is not None
    assert view["state"] == "FINISHED" and view["position_s"] == view["duration_s"] == 6000


def test_a_paused_replay_does_not_move():
    view = _replay_view(_row("PAUSED", 900, seconds_ago=1000), RUN)
    assert view is not None and view["state"] == "PAUSED" and view["position_s"] == 900


def test_me_names_the_caller_and_role_without_the_database(client):
    assert client.get("/api/v1/me").status_code == 401
    body = client.get("/api/v1/me", headers={"Authorization": f"Bearer {SUPERVISOR}"}).json()
    assert body == {"actor_id": "sup", "role": "MAINTENANCE_SUPERVISOR"}


def test_paths_outside_the_repository_are_refused(tmp_path):
    from fieldtwin_api.errors import ApiError
    from fieldtwin_api.results import read_json

    (tmp_path / "inside.json").write_text("{}")
    assert read_json(tmp_path, "inside.json", "x")[0] == {}
    with pytest.raises(ApiError) as refused:
        read_json(tmp_path, "../outside.json", "x")
    assert refused.value.code == "PATH_OUTSIDE_REPOSITORY"
