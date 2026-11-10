"""The dataset checksum follows file content and location, not just names and sizes."""

from __future__ import annotations

from pipelines.experiments.three_w_data import tree_sha256


def _tree(tmp_path, files: dict[str, bytes]):
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return tree_sha256(tmp_path, "dataset/*/*.parquet")


def test_a_same_size_content_change_changes_the_checksum(tmp_path):
    first = _tree(tmp_path / "a", {"dataset/1/X.parquet": b"aaaa"})
    second = _tree(tmp_path / "b", {"dataset/1/X.parquet": b"bbbb"})
    assert first != second


def test_files_sharing_a_name_in_different_folders_are_distinguished(tmp_path):
    one = _tree(tmp_path / "a", {"dataset/1/X.parquet": b"aaaa", "dataset/7/X.parquet": b"bbbb"})
    swapped = _tree(
        tmp_path / "b", {"dataset/1/X.parquet": b"bbbb", "dataset/7/X.parquet": b"aaaa"}
    )
    assert one != swapped


def test_the_same_tree_gives_the_same_checksum(tmp_path):
    files = {"dataset/1/X.parquet": b"aaaa", "dataset/2/Y.parquet": b"cc"}
    assert _tree(tmp_path / "a", files) == _tree(tmp_path / "b", files)
