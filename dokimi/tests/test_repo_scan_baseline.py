# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""`repo scan --baseline`: failing claims marked new or existing against the same source at a revision."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dokimi.artifacts import load_artifact
from dokimi.cli import build_parser

MANIFEST = {
    "schema": "repo_manifest.v1",
    "id": "toy",
    "source": {"url": "https://github.com/acme/toy"},
    "eval_dir": "dev/evals",
    "guidance": {"globs": ["**/AGENTS.md"], "also_scan": ["CONTRIBUTING.md"]},
    "entry_points": {"grade": "true"},
    "tasks": "dev/evals/tasks",
}
BASE_FILES = {
    "AGENTS.md": "# Toy\n[a](gone_a.md) and [ok](docs/x.md)\n[b](gone_b.md)\n",
    "CONTRIBUTING.md": "See [c](gone_c.md) and [d](docs/y.md).\n",
    "docs/x.md": "x\n",
    "docs/y.md": "y\n",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def _commit(root: Path, files: dict[str, str | None]) -> str:
    """Write ``files`` (None deletes), commit, and return the commit SHA."""
    for rel, text in files.items():
        path = root / rel
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "c")
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def toy(tmp_path):
    """A repository whose second commit moves a failing claim, adds one, fixes one and leaves one alone."""
    root = tmp_path / "toy"
    root.mkdir()
    _git(root, "init", "-q")
    base = _commit(root, BASE_FILES)
    head = _commit(root, {"AGENTS.md": "# Toy\n\nNew intro line.\n[a](gone_a.md) and [ok](docs/x.md)\n"
                                       "[new](gone_new.md)\n"})
    manifest_file = tmp_path / "m.json"
    manifest_file.write_text(json.dumps(MANIFEST), encoding="utf-8")
    return root, base, head, str(manifest_file)


def _scan(root: Path, manifest: str, *extra: str, at: str | None = None) -> dict:
    out = root.parent / "out.json"
    source = f"{root}@{at}" if at else str(root)
    assert _exit_code(["repo", "scan", source, "--manifest-file", manifest, "--out", str(out), *extra]) is None
    return load_artifact("repo_readiness", out)


def _exit_code(argv: list[str]) -> int | str | None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except SystemExit as exc:
        return exc.code
    return None


def _flags(payload: dict) -> dict[str, bool]:
    return {c["claim"]: c["new"] for c in payload["claims"] if "new" in c}


def test_a_failing_claim_is_new_by_file_kind_and_claim_never_by_line(toy):
    root, base, head, manifest = toy
    payload = _scan(root, manifest, "--baseline", base, at=head)
    # gone_a.md moved from line 2 to line 4 and stays existing; gone_c.md did not move
    assert _flags(payload) == {"gone_a.md": False, "gone_new.md": True, "gone_c.md": False}
    summary = payload["baseline"]
    assert (summary["new"], summary["existing"], summary["fixed"]) == (1, 2, 1)
    assert summary["sha"] == base and summary["rev"] == base and not summary["changed_only"]
    assert summary["changed_files"] is None and not summary["incomplete_new"]


def test_the_head_may_be_a_working_tree_with_uncommitted_changes(toy):
    root, base, _, manifest = toy
    (root / "CONTRIBUTING.md").write_text("See [e](gone_e.md).\n", encoding="utf-8")
    payload = _scan(root, manifest, "--baseline", base)
    assert payload["repo"]["sha"] is None
    assert _flags(payload)["gone_e.md"] is True and _flags(payload)["gone_a.md"] is False


def test_changed_only_limits_new_to_files_that_differ_from_the_baseline(toy):
    root, base, head, manifest = toy
    # docs/y.md is deleted: CONTRIBUTING.md is untouched yet its link to it now fails
    head = _commit(root, {"docs/y.md": None, "AGENTS.md": "# Toy\n[a](gone_a.md)\n[new](gone_new.md)\n"})
    everywhere = _scan(root, manifest, "--baseline", base, at=head)
    assert _flags(everywhere)["docs/y.md"] is True
    limited = _scan(root, manifest, "--baseline", base, "--changed-only", at=head)
    assert _flags(limited) == {"gone_a.md": False, "gone_new.md": True, "gone_c.md": False, "docs/y.md": False}
    assert limited["baseline"]["changed_only"] and limited["baseline"]["changed_files"] == ["AGENTS.md"]
    assert limited["baseline"]["new"] == 1


def test_fail_on_new_exits_1_only_for_a_new_failing_claim(toy, capsys):
    root, base, head, manifest = toy
    argv = ["repo", "scan", f"{root}@{head}", "--manifest-file", manifest, "--baseline"]
    assert _exit_code([*argv, base, "--fail-on-new"]) == 1
    assert "1 new failing claim(s) since " in capsys.readouterr().err
    # against itself nothing is new, though two claims fail: --fail-on-fail still exits 1
    assert _exit_code([*argv, head, "--fail-on-new"]) is None
    assert capsys.readouterr().err == ""
    assert _exit_code([*argv, head, "--fail-on-fail"]) == 1


def test_fail_on_new_exits_1_when_only_the_head_is_incomplete(toy, capsys):
    root, base, _, manifest = toy
    head = _commit(root, {"CONTRIBUTING.md": None, "AGENTS.md": BASE_FILES["AGENTS.md"]})
    argv = ["repo", "scan", f"{root}@{head}", "--manifest-file", manifest, "--baseline", base, "--fail-on-new"]
    assert _exit_code(argv) == 1
    err = capsys.readouterr().err
    assert f"scan incomplete, new since {base}: guidance/also_scan matches no file: CONTRIBUTING.md" in err
    assert "new failing claim" not in err
    # the same head as its own baseline is incomplete in both: not a new problem
    assert _exit_code(argv[:-2] + [head, "--fail-on-new"]) is None


def test_the_text_summary_names_the_new_claims_and_the_counts(toy, capsys):
    root, base, head, manifest = toy
    assert _exit_code(["repo", "scan", f"{root}@{head}", "--manifest-file", manifest, "--baseline", base,
                       "--changed-only"]) is None
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith(f"  baseline {base} (") and line.endswith(
        "failing claims 1 new, 2 existing, 1 fixed, 1 guidance files changed") for line in lines)
    assert [line for line in lines if " FAIL " in line and "gone_new.md" in line][0].startswith("  NEW FAIL AGENTS.md:")
    assert [line for line in lines if "gone_c.md" in line][0].startswith("  FAIL CONTRIBUTING.md:")


def test_a_report_without_a_baseline_is_unchanged(toy):
    root, _, head, manifest = toy
    payload = _scan(root, manifest, at=head)
    assert "baseline" not in payload and not any("new" in c for c in payload["claims"])


@pytest.mark.parametrize("extra", [["--fail-on-new"], ["--changed-only"]])
def test_a_baseline_flag_without_baseline_is_a_usage_error(toy, capsys, extra):
    root, _, head, manifest = toy
    assert _exit_code(["repo", "scan", f"{root}@{head}", "--manifest-file", manifest, *extra]) == 2
    assert f"✗ {extra[0]} needs --baseline <rev>" in capsys.readouterr().err


def test_baseline_with_static_is_a_usage_error(toy, tmp_path, capsys):
    root, base, head, manifest = toy
    static = tmp_path / "static.json"
    static.write_text(json.dumps({"schema": "repo_static.v1", "claims": []}), encoding="utf-8")
    assert _exit_code(["repo", "scan", f"{root}@{head}", "--manifest-file", manifest, "--baseline", base,
                       "--static", str(static)]) == 2
    assert "--baseline cannot be combined with --static" in capsys.readouterr().err


def test_an_unknown_baseline_revision_exits_1(toy, capsys):
    root, _, head, manifest = toy
    assert _exit_code(["repo", "scan", f"{root}@{head}", "--manifest-file", manifest, "--baseline", "nope"]) == 1
    assert capsys.readouterr().err.startswith("✗ ")


def test_an_unknown_baseline_revision_names_the_revision(toy, capsys):
    root, _, head, manifest = toy
    assert _exit_code(["repo", "scan", f"{root}@{head}", "--manifest-file", manifest, "--baseline", "nope"]) == 1
    assert capsys.readouterr().err.startswith("✗ baseline nope: ")


def test_an_empty_baseline_revision_is_a_usage_error(toy, capsys):
    root, _, head, manifest = toy
    assert _exit_code(["repo", "scan", f"{root}@{head}", "--manifest-file", manifest, "--baseline", ""]) == 2
    assert "--baseline needs a revision" in capsys.readouterr().err


def test_a_subdirectory_source_with_a_baseline_is_a_usage_error(toy, capsys):
    root, base, head, manifest = toy
    assert _exit_code(["repo", "scan", f"{root / 'docs'}@{head}", "--manifest-file", manifest, "--baseline",
                       base]) == 2
    assert capsys.readouterr().err.startswith("✗ ")


def test_the_kind_is_part_of_the_key(toy):
    root, base, _, manifest = toy
    # the same target text failed as a link in the baseline; as a path it is a different claim
    base = _commit(root, {"AGENTS.md": "[t](docs/gone_k.md)\n"})
    head = _commit(root, {"AGENTS.md": "see `docs/gone_k.md`\n"})
    payload = _scan(root, manifest, "--baseline", base, at=head)
    kinds = {c["kind"]: c["new"] for c in payload["claims"] if c["claim"] == "docs/gone_k.md" and "new" in c}
    assert kinds and all(kinds.values()) and "link" not in kinds


def test_a_renamed_guidance_file_makes_its_failing_claims_new(toy):
    root, base, _, manifest = toy
    _git(root, "mv", "AGENTS.md", "docs/AGENTS.md")
    head = _commit(root, {})
    for extra in ([], ["--changed-only"]):
        payload = _scan(root, manifest, "--baseline", base, *extra, at=head)
        flags = {(c["file"], c["claim"]): c["new"] for c in payload["claims"] if "new" in c}
        assert flags[("docs/AGENTS.md", "gone_a.md")] is True
        assert flags[("CONTRIBUTING.md", "gone_c.md")] is False
    assert payload["baseline"]["changed_files"] == ["docs/AGENTS.md"]


def test_a_deleted_guidance_file_counts_its_failures_as_fixed(toy):
    root, base, _, manifest = toy
    head = _commit(root, {"AGENTS.md": None})
    payload = _scan(root, manifest, "--baseline", base, "--changed-only", at=head)
    assert payload["baseline"]["fixed"] == 2 and payload["baseline"]["changed_files"] == []


def test_a_second_copy_of_a_failing_claim_is_new(toy):
    root, base, _, manifest = toy
    head = _commit(root, {"AGENTS.md": BASE_FILES["AGENTS.md"] + "[a again](gone_a.md)\n"})
    payload = _scan(root, manifest, "--baseline", base, at=head)
    copies = [c["new"] for c in payload["claims"] if c.get("claim") == "gone_a.md" and "new" in c]
    assert sorted(copies) == [False, True]
    dropped = _commit(root, {"AGENTS.md": "# Toy\n[ok](docs/x.md)\n[b](gone_b.md)\n"})
    assert _scan(root, manifest, "--baseline", head, at=dropped)["baseline"]["fixed"] == 2


def test_a_new_incomplete_reason_trips_the_gate_though_the_baseline_was_incomplete(toy, tmp_path, capsys):
    root, _, _, _ = toy
    two = tmp_path / "two.json"
    two.write_text(json.dumps({**MANIFEST, "guidance": {"globs": ["**/AGENTS.md"],
                                                        "also_scan": ["CONTRIBUTING.md", "DOCS.md"]}}),
                   encoding="utf-8")
    base = _commit(root, {"CONTRIBUTING.md": None, "DOCS.md": "d\n"})
    head = _commit(root, {"CONTRIBUTING.md": "c\n", "DOCS.md": None})
    argv = ["repo", "scan", f"{root}@{head}", "--manifest-file", str(two), "--baseline", base]
    assert _exit_code([*argv, "--fail-on-new"]) == 1
    err = capsys.readouterr().err
    assert "DOCS.md" in err and "CONTRIBUTING.md" not in err.split("new since", 1)[1]
    assert _exit_code(argv) is None
    out = capsys.readouterr().out.splitlines()
    assert len([line for line in out if line.startswith("  incomplete:")]) == 1
    assert "new since " in [line for line in out if line.startswith("  incomplete:")][0]
