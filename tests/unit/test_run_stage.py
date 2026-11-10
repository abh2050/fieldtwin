"""Every stage attempt is kept, including failures, with result hashes before and after."""

from __future__ import annotations

import json

from pipelines.experiments import run_stage


def test_a_failed_attempt_is_recorded_with_its_output(tmp_path, monkeypatch):
    monkeypatch.setattr(run_stage, "ATTEMPTS", tmp_path / "attempts")
    monkeypatch.setattr(run_stage, "RESULTS", tmp_path / "results")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "a.json").write_text("{}")
    code = run_stage.run("demo", "json.tool", ["no-such-file.json"])
    assert code != 0
    records = [
        json.loads(line)
        for line in (tmp_path / "attempts" / "attempts.jsonl").read_text().splitlines()
    ]
    assert len(records) == 1
    record = records[0]
    assert record["stage"] == "demo" and record["exit_code"] == code
    assert (
        record["results_before_sha256"] == record["results_after_sha256"]
        and record["results_changed"] == []
    )
    assert (tmp_path / "attempts" / record["log"]).read_text()


def test_a_changed_result_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(run_stage, "ATTEMPTS", tmp_path / "attempts")
    monkeypatch.setattr(run_stage, "RESULTS", tmp_path / "results")
    (tmp_path / "results").mkdir()
    before = run_stage.results_state()
    (tmp_path / "results" / "b.json").write_text("{}")
    assert set(run_stage.results_state()) - set(before) == {"b.json"}
