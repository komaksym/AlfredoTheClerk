# Active Implementation Plan

The current implementation slice is the post-repair correctness pipeline.

- Design: `docs/superpowers/specs/2026-07-14-post-repair-correctness-design.md`
- Execution plan: `docs/superpowers/plans/2026-07-14-post-repair-correctness.md`
- Branch: `codex/post-repair-correctness`

## Milestones

1. Extract reusable local FA(3) XSD validation.
2. Implement the shared correctness result and pipeline.
3. Gate agent repair outcomes through the correctness pipeline.
4. Update `SPEC.md` and run all repository validation gates.
