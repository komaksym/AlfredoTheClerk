# Active Implementation Plan

The current implementation slice is the backend human-review workflow.
Status: planned (2026-07-18).

- Design: `docs/superpowers/specs/2026-07-17-human-review-workflow-design.md`
- Execution plan: `docs/superpowers/plans/2026-07-18-human-review-workflow.md`
- Branch: `codex/human-review-workflow`
- Base: `codex/post-repair-correctness`

## Milestones

1. [ ] Share safe shell-field access without weakening agent constraints.
2. [ ] Build complete review cases from manual workflow outcomes.
3. [ ] Apply attributed human corrections atomically and retain failed attempts.
4. [ ] Resume through real correctness, XML, and local XSD validation.
5. [ ] Prove the persisted PDF-to-review-to-XSD integration path.
6. [ ] Update `SPEC.md` and pass lint, tests, compile, build, and wheel smoke gates.
