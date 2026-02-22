# Evaluation Gates

Last updated: 2026-02-22

This document defines how evaluation and security checks move from monitoring to blocking.

## Goals
- Prevent regressions on grounded answers, citations, and policy metadata.
- Keep security scans actionable without leaking sensitive content in CI logs/artifacts.
- Tighten gates incrementally to avoid noisy failures.

## Gate Levels
- `informational`: run, collect artifacts, never block merge.
- `warning`: non-blocking, but failure requires triage note in PR.
- `blocking`: failure blocks merge.

## Current Gate Status
- `tests` job: `blocking`.
- `policy-smoke` job: `blocking`.
- `security` job (`gitleaks`, `trivy`, `syft`): `blocking`.
- `osv-scan`: `blocking`.
- `promptfoo-eval`: `blocking` on core invariants.

## Promptfoo Blocking Invariants
`promptfoo` must satisfy all of the following:
- Result artifact exists and is parseable JSON.
- At least one evaluated row exists.
- Every test row has:
  - `success == true`
  - `gradingResult.pass == true`
  - HTTP status `200`.

Implementation:
- Runner: `scripts/run_promptfoo_eval.sh`
- Gate validator: `scripts/check_promptfoo_results.py`
- CI job: `.github/workflows/ci.yml` (`promptfoo-eval`)

## Security Scan Log/Artifact Policy
- Raw backend logs are not printed in CI output.
- Raw prompt/response transcripts are not uploaded as artifacts by default.
- CI should expose only sanitized summaries and metadata.

## Next Tightening Step
- Introduce non-blocking `garak` checks in CI with sanitized summary-only artifacts.
- After baseline stability, promote selected `garak` checks to `blocking`.
