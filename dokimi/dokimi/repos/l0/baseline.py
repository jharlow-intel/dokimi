# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Which failing claims of an L0 scan are new since a baseline scan of the same source (contract §8)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..source import RepoTree
from ..static import status_class

__all__ = ["changed_files", "mark_new"]


def _failing(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in claims if status_class(c["status"]) == "fail"]


def _key(claim: dict[str, Any]) -> tuple[str, str, str]:
    """File, kind and claim text, never the line: an edit above a claim moves it."""
    return claim["file"], str(claim.get("kind")), str(claim.get("claim"))


def changed_files(head: RepoTree, base: RepoTree, files: list[str]) -> list[str]:
    """The ``files`` whose text differs between ``base`` and ``head``, or that ``base`` lacks."""
    head_text = head.read_many(files)
    base_text = base.read_many(files)
    return [f for f in files if head_text.get(f) != base_text.get(f)]


def mark_new(head: dict[str, Any], base: dict[str, Any], base_tree: RepoTree, rev: str,
             changed: list[str] | None) -> None:
    """Set ``new`` on each failing claim of ``head`` and add its ``baseline`` summary.

    A failing claim is existing while the baseline has an unmatched failure with the same
    (file, kind, claim); a further copy is new. With ``changed`` (the guidance files that
    differ from the baseline), a failure in any other file is existing. ``incomplete_new``:
    the head scan has a reason the baseline's lacks.
    """
    left = Counter(_key(c) for c in _failing(base["claims"]))
    seen = Counter(left)
    scope = None if changed is None else set(changed)
    failing = _failing(head["claims"])
    for claim in failing:
        key = _key(claim)
        matched = left[key] > 0
        left[key] -= matched
        claim["new"] = not matched and (scope is None or claim["file"] in scope)
    new = sum(c["new"] for c in failing)
    reasons = [r for r in head["incomplete_reasons"] if r not in base["incomplete_reasons"]]
    head["baseline"] = {
        "rev": rev,
        "sha": getattr(base_tree, "sha", None),
        "tree": base_tree.label,
        "changed_only": changed is not None,
        "changed_files": changed,
        "new": new,
        "existing": len(failing) - new,
        "fixed": sum(left[k] for k in seen if left[k] > 0),
        "incomplete": base["incomplete"],
        "incomplete_new": bool(reasons),
        "incomplete_new_reasons": reasons,
    }
