# Add GenLedge Agent Instructions

## Plan

- [x] Confirm the initial working tree was clean and `Agent-instruction` did not already exist.
- [x] Fetch the latest `origin/main` and fast-forward local `main`.
- [x] Align `Agent-instruction` with the updated `main` commit (`c096c0f`).
- [x] Add repository-agnostic agent guidance at `dot_codex/AGENTS.md`.
- [x] State that README files must not be changed unless the user specifically requests it.
- [x] Verify the instruction file and this plan, run `git diff --check`, and confirm no README has a local working-tree change.
- [x] Save the completed plan in `doc/`.

## Review

`Agent-instruction` points to the fetched `main` commit `c096c0f1dd2b2f8ee687b20cf5e20573ac8d01ac`. The agent instructions, working plan, and completed plan copy are present. `git diff --check` passes; no README has a local working-tree change. No application tests were needed for this instruction-only task.
