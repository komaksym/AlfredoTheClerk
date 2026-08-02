# Agentic Repair Benchmark Review-Fix Plan

## Goal

Address the three validated independent-review findings without changing the
production repair policy:

1. fail live benchmark workflows that are not publishable;
2. separate generated sanity coverage from a held-out headline corpus;
3. reject incomplete case/run matrices before scoring.

## TDD sequence

- [x] Add a CLI regression where every model attempt errors, reports are still
  written, and the exit code must be nonzero.
- [x] Add scoring regressions for a missing case/run combination.
- [x] Add corpus regressions requiring a 30-case held-out split, neutral
  candidate metadata, varied expected indexes, and varied confidence ranks.
- [x] Run CI and confirm the new tests fail before production changes.
- [x] Add the headline publication boundary and hard corpus.
- [x] Add the complete Cartesian matrix check.
- [x] Add the post-report publication gate with a default 5% error threshold.
- [x] Keep the original generated 200-case corpus as byte-reproducible sanity
  coverage only.
- [ ] Run the complete repository gates on the final merge commit.
- [ ] Update the PR description with final verification evidence.

## Verification commands

```bash
uv run ruff check .
uv run pyright src tests
uv run pytest -q -m "not browser_e2e and not ksef_live"
uv run pytest -q -m browser_e2e
uv run python -m compileall src tests
uv build --wheel
uv run python tests/smoke_installed_xsd_validation.py \
  dist/alfredotheclerk-*.whl
```

The strict KSeF TEST job remains inherited from `main` and must also pass on the
final pull-request merge commit.
