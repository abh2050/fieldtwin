"""Generate machine-readable source schemas from the acquired records.

Profiles report types and fill rates, not record values, so they can be committed for a source with
no stated license. Documented types are shown beside observed ones so differences stay visible.
"""

from __future__ import annotations

import configparser
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd
import pyarrow.parquet as pq

from pipelines.acquire.common.core import REPO_ROOT

from .common import latest_complete

OUTPUT = Path("data_contracts/sources/generated")
_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+\.?\d*([eE][-+]?\d+)?$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$")


def infer_type(value: str) -> str:
    if _INT.match(value):
        return "integer"
    if _FLOAT.match(value):
        return "float"
    if _DATETIME.match(value):
        return "datetime"
    return "string"


def profile_string_column(series: pd.Series) -> dict[str, Any]:
    """Describe a bronze column by shape only. No values leave this function."""
    present = series.dropna().astype(str)
    blank = present.str.strip() == ""
    filled = present[~blank]
    lengths = present.str.len()
    types = Counter(infer_type(v.strip()) for v in filled.unique())
    return {
        "row_count": int(len(series)),
        "null_count": int(series.isna().sum()),
        "null_rate": round(float(series.isna().mean()), 4) if len(series) else 0.0,
        "blank_count": int(blank.sum()),
        "distinct_count": int(present.nunique()),
        "observed_types": sorted(types),
        "has_padding": bool((present != present.str.strip()).any()),
        "length_min": int(lengths.min()) if len(lengths) else None,
        "length_max": int(lengths.max()) if len(lengths) else None,
        "nullable_observed": bool(series.isna().any() or blank.any()),
    }


def read_dictionary(path: Path, table: str) -> dict[str, dict[str, str]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    columns = {}
    for row in workbook["data dictionary"].iter_rows(min_row=2, values_only=True):
        if row[1] == table and row[2]:
            cells = [c for c in row[3:] if c is not None]
            declared = next(
                (str(c).strip() for c in cells if re.match(r"^[a-z]+(\(.*\))?$", str(c))), None
            )
            columns[str(row[2]).strip()] = {
                "documented_type": declared or "",
                "documented_description": str(row[-1] or "").strip(),
            }
    return columns


def arcgis_fields(path: Path) -> dict[str, dict[str, str]]:
    metadata = json.loads(path.read_text())
    return {
        f["name"]: {"documented_type": f["type"], "documented_description": f.get("alias", "")}
        for f in metadata.get("fields", [])
    }


def ocd_schema(root: Path) -> dict[str, Any]:
    manifest = latest_complete(root, "nm_ocd")
    batch = manifest["batch_id"]
    bronze = root / "data" / "bronze" / "nm_ocd" / batch
    raw = root / "data" / "raw" / "nm_ocd" / manifest["source_version"] / batch
    hashes = {Path(f["path"]).name: f["sha256"] for f in manifest["files"]}
    dictionary = raw / "ftp" / "OCD Interface v1.1 Data Dictionary.xlsx"
    documented = {
        "wells": (arcgis_fields(raw / "arcgis" / "layer_metadata.json"), "arcgis/page_*.json"),
        "wellhistory": (read_dictionary(dictionary, "wellhistory"), "wellhistory.zip"),
        "wcproduction": (read_dictionary(dictionary, "wcproduction"), "wcproduction.zip"),
    }
    datasets = {}
    for name, (fields, raw_name) in documented.items():
        frame = pd.read_parquet(bronze / f"{name}.parquet")
        columns = {}
        for column in frame.columns:
            columns[column] = {
                **profile_string_column(frame[column]),
                **fields.get(column, {}),
                "in_source_documentation": column in fields,
            }
        datasets[name] = {
            "bronze_file": f"data/bronze/nm_ocd/{batch}/{name}.parquet",
            "raw_file": raw_name,
            "raw_sha256": hashes.get(raw_name),
            "row_count": len(frame),
            "columns": columns,
            "documented_columns_not_in_bronze": sorted(set(fields) - set(frame.columns)),
        }
    return {
        "source_system_id": "nm_ocd",
        "generated_from_batch": batch,
        "lineage": "raw zip or ArcGIS page -> pipelines/acquire/nm_ocd -> bronze Parquet of original text",
        "values_included": False,
        "datasets": datasets,
    }


def w3_schema(root: Path) -> dict[str, Any]:
    manifest = latest_complete(root, "petrobras_3w")
    batch = manifest["batch_id"]
    raw = root / "data" / "raw" / "petrobras_3w" / manifest["source_version"] / batch
    index = pd.read_parquet(root / "data" / "bronze" / "petrobras_3w" / batch / "instances.parquet")
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(raw / "dataset" / "dataset.ini")
    documented = dict(parser["PARQUET_FILE_PROPERTIES"])

    columns: dict[str, dict[str, Any]] = {}
    for row in index.itertuples():
        parquet = pq.ParquetFile(raw / row.source_path)
        table = parquet.read()
        origin = row.real_or_simulated_source
        for name in table.schema.names:
            column = table[name]
            entry = columns.setdefault(
                name,
                {
                    "physical_types": set(),
                    "documented_description": documented.get(name),
                    "by_origin": {},
                },
            )
            entry["physical_types"].add(str(table.schema.field(name).type))
            stats = entry["by_origin"].setdefault(
                origin, {"instances": 0, "rows": 0, "nulls": 0, "instances_entirely_null": 0}
            )
            stats["instances"] += 1
            stats["rows"] += table.num_rows
            stats["nulls"] += column.null_count
            stats["instances_entirely_null"] += int(column.null_count == table.num_rows)
    for entry in columns.values():
        entry["physical_types"] = sorted(entry["physical_types"])
        for stats in entry["by_origin"].values():
            stats["null_rate"] = round(stats["nulls"] / stats["rows"], 4) if stats["rows"] else 0.0
        entry["nullable_observed"] = any(s["nulls"] for s in entry["by_origin"].values())
    return {
        "source_system_id": "petrobras_3w",
        "generated_from_batch": batch,
        "dataset_version": manifest["source_version"],
        "commit": manifest["datasets"]["commit"],
        "lineage": "raw Parquet at the pinned commit; bronze holds an instance index only",
        "instances_profiled": len(index),
        "instance_id_repeats_across_classes": int(index["source_instance_id"].duplicated().sum()),
        "documented_columns_not_observed": sorted(set(documented) - set(columns)),
        "observed_columns_not_documented": sorted(set(columns) - set(documented)),
        "columns": dict(sorted(columns.items())),
    }


def main(root: Path = REPO_ROOT) -> int:
    output = root / OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    for name, build in (("nm_ocd", ocd_schema), ("petrobras_3w", w3_schema)):
        path = output / f"{name}.schema.json"
        path.write_text(json.dumps(build(root), indent=2, sort_keys=True) + "\n")
        print(f"wrote {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
