"""Petrobras 3W acquisition: a deterministic subset at a pinned commit, verified file by file.

3W describes offshore wells. Nothing here is linked to AETHER Field or to any New Mexico well.
"""

from __future__ import annotations

import configparser
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from pipelines.acquire.common import core
from pipelines.acquire.common.core import BatchManifest, FileEntry, Quarantine
from pipelines.acquire.common.errors import ChecksumMismatch, MalformedSource, SchemaDrift
from pipelines.acquire.common.transport import Http

SOURCE = "petrobras_3w"
RAW_URL = "https://raw.githubusercontent.com/{repo}/{commit}/{path}"
TREE_URL = "https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1"
_LOG = core.get_logger("acquire.petrobras_3w")

_NAME = re.compile(
    r"^(?:WELL-(?P<well>\d{5})_(?P<ts>\d{14})|SIMULATED_(?P<sim>\d{5})|DRAWN_(?P<drawn>\d{5}))"
    r"\.parquet$"
)
_DATA_PATH = re.compile(r"^dataset/(?P<label>\d)/(?P<name>[^/]+\.parquet)$")
REAL, SIMULATED, HAND_DRAWN = "REAL", "SIMULATED", "HAND_DRAWN"


@dataclass(frozen=True)
class Instance:
    path: str
    label: int
    origin: str
    source_well_id: str | None
    source_instance_id: str
    git_blob_sha: str
    size_bytes: int

    @property
    def provenance_class(self) -> str:
        """Only real wells are OBSERVED. Upstream-generated series stay SYNTHETIC."""
        return "OBSERVED" if self.origin == REAL else "SYNTHETIC"


def parse_instance(entry: dict[str, Any]) -> Instance | None:
    """Parse a tree entry. An unrecognized name returns None and is never assumed to be real."""
    path_match = _DATA_PATH.match(entry["path"])
    if not path_match:
        return None
    name_match = _NAME.match(path_match["name"])
    if not name_match:
        return None
    if name_match["well"]:
        origin, well = REAL, f"WELL-{name_match['well']}"
    elif name_match["sim"]:
        origin, well = SIMULATED, None
    else:
        origin, well = HAND_DRAWN, None
    return Instance(
        path=entry["path"],
        label=int(path_match["label"]),
        origin=origin,
        source_well_id=well,
        source_instance_id=path_match["name"].removesuffix(".parquet"),
        git_blob_sha=entry["sha"],
        size_bytes=entry["size"],
    )


def _round_robin_by_well(instances: list[Instance], cap: int) -> list[Instance]:
    """Take from each well in turn so a capped class still spans many wells."""
    by_well: dict[str, list[Instance]] = {}
    for instance in sorted(instances, key=lambda i: i.path):
        by_well.setdefault(instance.source_well_id or "", []).append(instance)
    chosen: list[Instance] = []
    wells = sorted(by_well)
    depth = 0
    while len(chosen) < cap and any(depth < len(by_well[w]) for w in wells):
        for well in wells:
            if depth < len(by_well[well]) and len(chosen) < cap:
                chosen.append(by_well[well][depth])
        depth += 1
    return chosen


def _evenly_spaced(instances: list[Instance], count: int) -> list[Instance]:
    ordered = sorted(instances, key=lambda i: i.path)
    if len(ordered) <= count:
        return ordered
    return [ordered[i * len(ordered) // count] for i in range(count)]


def select_instances(instances: list[Instance], selection: dict[str, Any]) -> list[Instance]:
    """Pick the subset using only names and config, so the same tree gives the same result."""
    chosen: list[Instance] = []
    caps = {int(k): v for k, v in selection["real_cap_by_class"].items()}
    for label in sorted({i.label for i in instances}):
        group = [i for i in instances if i.label == label]
        real = [i for i in group if i.origin == REAL]
        chosen += _round_robin_by_well(real, caps.get(label, len(real)))
        chosen += _evenly_spaced(
            [i for i in group if i.origin == SIMULATED], selection["simulated_per_class"]
        )
        chosen += _evenly_spaced(
            [i for i in group if i.origin == HAND_DRAWN], selection["drawn_per_class"]
        )
    return sorted(chosen, key=lambda i: i.path)


def fetch_verified(http: Http, url: str, dest: Path, blob_sha: str) -> None:
    """Write a file only after its bytes match the Git blob hash in the pinned tree."""
    if dest.exists() and core.git_blob_sha1(dest.read_bytes()) == blob_sha:
        return
    data = http.get_bytes(url)
    actual = core.git_blob_sha1(data)
    if actual != blob_sha:
        raise ChecksumMismatch(f"{url}: expected blob {blob_sha}, received {actual}.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + ".part")
    temp.write_bytes(data)
    temp.replace(dest)


def read_dataset_version(ini_path: Path) -> str:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ini_path)
    try:
        return parser["VERSION"]["DATASET"].strip()
    except KeyError as exc:
        raise SchemaDrift("dataset.ini has no [VERSION] DATASET value.") from exc


def event_names(ini_path: Path) -> dict[int, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ini_path)
    names = [n.strip() for n in parser["EVENTS"]["NAMES"].replace("\n", " ").split(",")]
    return {int(parser[name]["LABEL"]): name for name in names}


def index_row(instance: Instance, path: Path, batch_id: str, names: dict[int, str]) -> dict:
    """Read Parquet metadata so a damaged file fails here, not in a later gate."""
    try:
        rows = pq.ParquetFile(path).metadata.num_rows
    except Exception as exc:
        raise MalformedSource(f"{instance.path} is not readable Parquet: {exc}") from exc
    return {
        "source_instance_id": instance.source_instance_id,
        "source_path": instance.path,
        "source_event_label": instance.label,
        "source_event_class": names.get(instance.label),
        "real_or_simulated_source": instance.origin,
        "source_well_id": instance.source_well_id,
        "row_count": rows,
        "git_blob_sha": instance.git_blob_sha,
        "provenance_class": instance.provenance_class,
        "source_batch_id": batch_id,
    }


def run(
    root: Path = core.REPO_ROOT,
    refresh: bool = False,
    http: Http | None = None,
    disk_usage: Any = None,
) -> dict[str, Any]:
    """Acquire the subset and return its manifest. Any failure raises before COMPLETE is written."""
    cfg = core.load_yaml(root / "config" / "sources" / "petrobras_3w.yaml")
    config_sha = core.config_hash(cfg)
    if not refresh and (existing := core.find_complete(root, SOURCE, config_sha)):
        core.log(_LOG, "reusing completed batch", batch_id=existing["batch_id"])
        return {**existing, "reused": True}

    http = http or Http()
    repo, commit = cfg["repo"], cfg["commit"]
    tree_body = http.get_bytes(TREE_URL.format(repo=repo, commit=commit))
    tree = json.loads(tree_body)
    if tree.get("truncated"):
        raise MalformedSource("GitHub truncated the tree listing, so selection would be partial.")
    blobs = {e["path"]: e for e in tree["tree"] if e["type"] == "blob"}

    version = cfg["expected_dataset_version"]
    batch_id = f"{SOURCE}-{version}-{commit[:10]}-{config_sha[:10]}"
    raw_dir = root / "data" / "raw" / SOURCE / version / batch_id
    bronze_dir = root / "data" / "bronze" / SOURCE / batch_id
    if finished := core.completed_batch(root, SOURCE, batch_id):
        core.log(_LOG, "commit already acquired; raw is immutable", batch_id=batch_id)
        return {**finished, "reused": True}
    quarantine = Quarantine(bronze_dir / "quarantine.jsonl")

    instances: list[Instance] = []
    for path, entry in blobs.items():
        if path.startswith("dataset/") and path.endswith(".parquet"):
            instance = parse_instance(entry)
            if instance:
                instances.append(instance)
            else:
                quarantine.add("tree", "UNRECOGNIZED_INSTANCE_NAME", entry)
    selected = select_instances(instances, cfg["selection"])

    needed = sum(i.size_bytes for i in selected)
    kwargs = {"disk_usage": disk_usage} if disk_usage else {}
    core.preflight_disk(root / "data", needed, cfg["disk_floor_bytes"], **kwargs)
    core.log(_LOG, "batch started", batch_id=batch_id, files=len(selected), bytes=needed)

    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "tree.json").write_bytes(tree_body)
    targets = [(p, blobs[p]["sha"]) for p in cfg["metadata_files"]]
    targets += [(i.path, i.git_blob_sha) for i in selected]

    def fetch(target: tuple[str, str]) -> None:
        path, sha = target
        fetch_verified(
            http, RAW_URL.format(repo=repo, commit=commit, path=path), raw_dir / path, sha
        )

    with ThreadPoolExecutor(max_workers=cfg["max_concurrent_downloads"]) as pool:
        list(pool.map(fetch, targets))  # list() re-raises the first failure.

    ini_path = raw_dir / "dataset" / "dataset.ini"
    actual_version = read_dataset_version(ini_path)
    if actual_version != version:
        raise SchemaDrift(f"Commit holds dataset {actual_version}, config expects {version}.")

    names = event_names(ini_path)
    rows = [index_row(i, raw_dir / i.path, batch_id, names) for i in selected]
    core.write_string_parquet(bronze_dir / "instances.parquet", rows, list(rows[0]))

    files = [
        FileEntry(
            path=core.rel(raw_dir / path, root),
            sha256=core.sha256_file(raw_dir / path),
            size_bytes=(raw_dir / path).stat().st_size,
            source_url=RAW_URL.format(repo=repo, commit=commit, path=path),
            upstream_checksum=f"git-blob-sha1:{sha}",
        )
        for path, sha in targets
    ]
    tree_path = raw_dir / "tree.json"
    files.append(
        FileEntry(
            path=core.rel(tree_path, root),
            sha256=core.sha256_file(tree_path),
            size_bytes=tree_path.stat().st_size,
            source_url=TREE_URL.format(repo=repo, commit=commit),
        )
    )
    core.freeze_tree(raw_dir)

    def tally(items: list[Instance]) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for item in items:
            group = counts.setdefault(str(item.label), {})
            group[item.origin] = group.get(item.origin, 0) + 1
        return counts

    manifest = BatchManifest(
        batch_id=batch_id,
        source_system_id=SOURCE,
        source_version=version,
        config_sha256=config_sha,
        ingestion_timestamp=core.utc_now(),
        original_checksum=core.aggregate_checksum(files),
        source_record_count=len(selected),
        accepted_count=len(rows),
        rejected_count=quarantine.count,
        processing_status=core.COMPLETE,
        manifest_uri=f"data/manifests/{SOURCE}/{batch_id}.json",
        license=cfg["license"],
        files=files,
        datasets={
            "commit": commit,
            "instances_available": tally(instances),
            "instances_selected": tally(selected),
            "instances_unit": "one Parquet file is one source instance",
        },
        notes=[
            "Every file was verified against the Git blob hash in the tree at the pinned commit.",
            "3W describes offshore wells. No record here was measured at a New Mexico or AETHER "
            "well.",
        ],
    )
    core.write_manifest(manifest, root)
    core.log(_LOG, "batch complete", batch_id=batch_id, files=len(files))
    return {**json.loads(core.manifest_path(root, SOURCE, batch_id).read_text()), "reused": False}
