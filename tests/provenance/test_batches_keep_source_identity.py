"""Checks on batches on disk. These need `make acquire`, so they are not in the default suite."""

import pandas as pd
import pytest

from pipelines.acquire.common.core import sha256_file
from pipelines.profile.common import latest_complete
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.acquired


def bronze(source: str, name: str) -> pd.DataFrame:
    batch = latest_complete(REPO_ROOT, source)["batch_id"]
    return pd.read_parquet(REPO_ROOT / "data/bronze" / source / batch / f"{name}.parquet")


def test_ocd_bronze_is_observed_and_contains_no_aether_reference():
    for name in ("wells", "wellhistory", "wcproduction"):
        frame = bronze("nm_ocd", name)
        assert set(frame["provenance_class"]) == {"OBSERVED"}
        assert (
            not frame.astype(str).apply(lambda c: c.str.contains("AETHER", case=False)).any().any()
        )


def test_3w_generated_instances_are_never_observed_or_tied_to_a_well():
    index = bronze("petrobras_3w", "instances")
    generated = index[index["real_or_simulated_source"] != "REAL"]
    assert len(generated) > 0
    assert set(generated["provenance_class"]) == {"SYNTHETIC"}
    assert generated["source_well_id"].isna().all()


def test_3w_real_instances_keep_their_source_well_in_the_identifier():
    real = bronze("petrobras_3w", "instances").query("real_or_simulated_source == 'REAL'")
    assert len(real) > 0
    ids = real["source_well_id"] + "_"
    assert all(i.startswith(w) for i, w in zip(real["source_instance_id"], ids, strict=True))


@pytest.mark.parametrize("source", ["nm_ocd", "petrobras_3w"])
def test_manifest_checksums_match_raw_files(source):
    manifest = latest_complete(REPO_ROOT, source)
    sample = manifest["files"][:25]
    assert all(sha256_file(REPO_ROOT / f["path"]) == f["sha256"] for f in sample)
