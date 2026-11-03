### Added

- **`repo scan --baseline <rev>` marks failing claims new or existing** — also scans the same source at
  `<rev>` with the same manifest and sets `new` on each failing claim of the head: existing when the baseline
  fails on the same file, kind and claim text (never the line), new otherwise. `--changed-only` makes a
  claim new only in a guidance file that differs from `<rev>`, so a pull request gates the files it touches;
  `--fail-on-new` exits 1 only for a new failing claim, or a scan that is incomplete where the baseline's was
  not. The text output gains a `baseline` line and `NEW FAIL` rows, and `repo_readiness.v1` an optional
  `baseline` object and a `new` flag on failing claims; reports without `--baseline` are unchanged. A flag that
  needs `--baseline` without it, and `--baseline` with `--static`, exit 2; an unknown `<rev>` exits 1. `repo scan --fail-on` was an abbreviation of `--fail-on-fail` and is now ambiguous: spell the flag out.
