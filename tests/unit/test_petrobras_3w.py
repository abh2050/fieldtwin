"""3W instance naming and deterministic selection."""

import random

from pipelines.acquire.petrobras_3w.adapter import (
    HAND_DRAWN,
    REAL,
    SIMULATED,
    parse_instance,
    select_instances,
)
from pipelines.profile.petrobras_3w import allowed_labels

SELECTION = {"real_cap_by_class": {0: 4}, "simulated_per_class": 2, "drawn_per_class": 2}


def entry(path, sha="a" * 40, size=10):
    return {"path": path, "sha": sha, "size": size, "type": "blob"}


def test_origin_comes_from_the_filename_and_real_ids_are_kept():
    real = parse_instance(entry("dataset/2/WELL-00012_20170201010207.parquet"))
    assert (real.origin, real.source_well_id) == (REAL, "WELL-00012")
    assert real.source_instance_id == "WELL-00012_20170201010207"
    assert real.provenance_class == "OBSERVED"


def test_generated_instances_never_get_a_well_id_or_observed_status():
    simulated = parse_instance(entry("dataset/5/SIMULATED_00001.parquet"))
    drawn = parse_instance(entry("dataset/7/DRAWN_00001.parquet"))
    assert (simulated.origin, drawn.origin) == (SIMULATED, HAND_DRAWN)
    assert simulated.source_well_id is None and drawn.source_well_id is None
    assert simulated.provenance_class == drawn.provenance_class == "SYNTHETIC"


def test_unrecognized_names_are_not_assumed_to_be_real():
    assert parse_instance(entry("dataset/2/OTHER_00001.parquet")) is None
    assert parse_instance(entry("dataset/demos/x.parquet")) is None


def build_instances():
    paths = [
        f"dataset/0/WELL-{w:05d}_2017020{i}000000.parquet" for w in (1, 2, 3) for i in range(5)
    ]
    paths += [f"dataset/1/SIMULATED_{i:05d}.parquet" for i in range(10)]
    paths += ["dataset/1/DRAWN_00001.parquet", "dataset/1/WELL-00009_20170201000000.parquet"]
    return [parse_instance(entry(p)) for p in paths]


def test_selection_is_deterministic_regardless_of_input_order():
    instances = build_instances()
    shuffled = instances[:]
    random.Random(7).shuffle(shuffled)
    assert select_instances(instances, SELECTION) == select_instances(shuffled, SELECTION)


def test_capped_class_spans_every_well():
    chosen = [i for i in select_instances(build_instances(), SELECTION) if i.label == 0]
    assert len(chosen) == 4
    assert {i.source_well_id for i in chosen} == {"WELL-00001", "WELL-00002", "WELL-00003"}


def test_uncapped_real_instances_are_all_kept_and_generated_ones_limited():
    chosen = [i for i in select_instances(build_instances(), SELECTION) if i.label == 1]
    assert sum(i.origin == REAL for i in chosen) == 1
    assert sum(i.origin == SIMULATED for i in chosen) == 2
    assert sum(i.origin == HAND_DRAWN for i in chosen) == 1


def test_allowed_labels_follow_the_transient_offset():
    assert allowed_labels(0) == {0}
    assert allowed_labels(7) == {0, 7, 107}
