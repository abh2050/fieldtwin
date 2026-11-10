"""Leakage-safe splits. A well, and every instance and window on it, stays on one side."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold


class SplitLeakage(ValueError):
    """A group appears on both sides of a split."""


@dataclass(frozen=True)
class WellFold:
    name: str
    train_wells: tuple[str, ...]
    validation_wells: tuple[str, ...]
    test_wells: tuple[str, ...]


def _assign(frame: pd.DataFrame, folds: int, seed: int) -> list[tuple[str, ...]]:
    """Partition wells so classes spread as evenly as the wells allow."""
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    groups = []
    for _, test in splitter.split(frame, frame["filed_class"], frame["source_well_id"]):
        groups.append(tuple(sorted(frame.iloc[test]["source_well_id"].unique())))
    return groups


def build_well_folds(
    instances: pd.DataFrame,
    *,
    holdout_folds: int,
    development_folds: int,
    validation_folds: int,
    seed: int,
) -> tuple[WellFold, list[WellFold]]:
    """Return the holdout fold and the development folds. All are grouped by well."""
    holdout_wells = _assign(instances, holdout_folds, seed)[0]
    development = instances[~instances["source_well_id"].isin(holdout_wells)]
    outer = _assign(development, development_folds, seed)

    def with_validation(name: str, frame: pd.DataFrame, test: tuple[str, ...]) -> WellFold:
        pool = frame[~frame["source_well_id"].isin(test)]
        validation = _assign(pool, validation_folds, seed)[0]
        train = sorted(set(pool["source_well_id"]) - set(validation))
        fold = WellFold(name, tuple(train), validation, test)
        assert_no_group_overlap(fold)
        return fold

    holdout = with_validation("holdout", instances, holdout_wells)
    folds = [with_validation(f"dev_{i}", development, test) for i, test in enumerate(outer)]
    return holdout, folds


def assert_no_group_overlap(fold: WellFold) -> None:
    train, validation, test = map(set, (fold.train_wells, fold.validation_wells, fold.test_wells))
    shared = (train & validation) | (train & test) | (validation & test)
    if shared:
        raise SplitLeakage(f"{fold.name}: wells on more than one side: {sorted(shared)}")


def class_coverage(instances: pd.DataFrame, fold: WellFold) -> pd.DataFrame:
    """Instances and wells per class on each side of a fold."""
    rows = []
    for side, wells in (
        ("train", fold.train_wells),
        ("validation", fold.validation_wells),
        ("test", fold.test_wells),
    ):
        part = instances[instances["source_well_id"].isin(wells)]
        for label, group in part.groupby("filed_class"):
            rows.append(
                {
                    "fold": fold.name,
                    "side": side,
                    "filed_class": int(label),
                    "instances": len(group),
                    "wells": group["source_well_id"].nunique(),
                }
            )
    return pd.DataFrame(rows)


def credible_classes(
    instances: pd.DataFrame, *, min_events: int, min_clusters: int
) -> pd.DataFrame:
    """Which classes have enough instances and wells to support any credible evaluation."""
    rows = []
    for label, group in instances.groupby("filed_class"):
        count, wells = len(group), group["source_well_id"].nunique()
        rows.append(
            {
                "filed_class": int(label),
                "instances": count,
                "wells": wells,
                "supports_evaluation": bool(count >= min_events and wells >= min_clusters),
                # Testing on an unseen well needs that class on some other well for training.
                "largest_well_share": round(
                    float(group["source_well_id"].value_counts(normalize=True).iloc[0]), 3
                ),
                "supports_unseen_well_claim": bool(wells >= 2),
            }
        )
    return pd.DataFrame(rows)
