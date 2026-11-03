# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""`repo scan`: the text report, and the CLI side of `--baseline` (failing claims new or existing, contract §8)."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from dokimi.exit_codes import EXIT_USAGE


def check_flags(args: argparse.Namespace) -> None:
    """Exit 2 on a flag that needs --baseline without it, an empty --baseline, or --static with it."""
    if args.baseline is None:
        for given, flag in ((args.changed_only, "--changed-only"), (args.fail_on_new, "--fail-on-new")):
            if given:
                print(f"✗ {flag} needs --baseline <rev>", file=sys.stderr)
                sys.exit(EXIT_USAGE)
    elif not args.baseline:
        print("✗ --baseline needs a revision", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    elif args.static:
        print("✗ --baseline cannot be combined with --static: its claims belong to one tree", file=sys.stderr)
        sys.exit(EXIT_USAGE)


def attach(payload: dict[str, Any], tree: Any, manifest: Any, base_tree: Any, args: argparse.Namespace) -> None:
    """Scan ``base_tree`` with the same manifest and add ``baseline`` and each failing claim's ``new`` to ``payload``."""
    from dokimi.repos.l0 import scan_repo
    from dokimi.repos.l0.baseline import changed_files, mark_new

    changed = changed_files(tree, base_tree, payload["files"]) if args.changed_only else None
    mark_new(payload, scan_repo(base_tree, manifest), base_tree, args.baseline, changed)


def _baseline_lines(payload: dict[str, Any]) -> list[str]:
    """The text lines for the report's ``baseline`` (none without one)."""
    base = payload.get("baseline")
    if base is None:
        return []
    scope = f", {len(base['changed_files'])} guidance files changed" if base["changed_only"] else ""
    lines = [f"  baseline {base['rev']} ({base['tree']}): failing claims {base['new']} new, "
             f"{base['existing']} existing, {base['fixed']} fixed{scope}"]
    return lines


def gate(payload: dict[str, Any], fail_on_new: bool) -> None:
    """--fail-on-new: exit 1 on a new failing claim or a scan incomplete where the baseline's was not."""
    base = payload.get("baseline")
    if not fail_on_new or base is None or not (base["new"] or base["incomplete_new"]):
        return
    if base["incomplete_new"]:
        print(f"✗ scan incomplete, new since {base['rev']}: {'; '.join(base['incomplete_new_reasons'])}",
              file=sys.stderr)
    if base["new"]:
        print(f"✗ {base['new']} new failing claim(s) since {base['rev']}", file=sys.stderr)
    sys.exit(1)


def print_report(payload: dict[str, Any], manifest_id: str, static_info: dict[str, Any] | None,
                 static_errors: list[str]) -> None:
    """The text summary of a scan: counts, warnings, the baseline line and each failing claim."""
    c = payload["counts"]
    detected = " (detected)" if payload["adapters_detected"] else ""
    print(f"{manifest_id}: {len(payload['files'])} guidance files in {payload['repo']['tree']}; "
          f"adapters: {', '.join(payload['adapters']) or 'none'}{detected}")
    print(f"  claims: {c['total']} (ok {c['ok']}, unresolved {c['unresolved']}, fail {c['fail']})")
    for warning in payload["warnings"]:
        print(f"  warning: {warning}")
    if payload["incomplete"]:
        news = (payload.get("baseline") or {}).get("incomplete_new_reasons", [])
        note = f"; new since {payload['baseline']['rev']}: {'; '.join(news)}" if news else ""
        print(f"  incomplete: {'; '.join(payload['incomplete_reasons'])} (repo scan --fail-on-fail exits 1{note})")
    for line in _baseline_lines(payload):
        print(line)
    if static_info is not None and not static_errors:
        r = payload["by_source"]["repository"]
        print(f"  repository static: {r['total']} claims, {r['fail']} fail; "
              f"{static_info['superseded']} framework claims replaced")
    for claim in payload["claims"]:
        if claim["status"].split("_", 1)[0] == "fail":
            tag = "NEW FAIL" if claim.get("new") else "FAIL"
            print(f"  {tag} {claim['file']}:{claim['line']} [{claim.get('kind')}] "
                  f"{str(claim.get('claim'))[:90]} -- {claim.get('why')}")
