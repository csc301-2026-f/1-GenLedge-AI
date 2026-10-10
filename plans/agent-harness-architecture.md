# Agent Harness Architecture Document

## Plan

- [x] Fetch the latest `origin/main` and create `harness-design` from it.
- [x] Read the existing backend, UI, and project planning documents to identify assumptions the new design changes.
- [x] Write a standalone architecture document describing source inputs, connector tools, the proposal loop, review output, and LangGraph orchestration.
- [x] Check the document against the agreed flow and inspect the diff for consistency and unintended changes.
- [x] Record verification results and save the finalized plan in `doc/`.

## Review

The `harness-design` branch is based on `origin/main` at `643277592192fae66880447e37b92a97c3a8e058`. The standalone architecture document covers source snapshots, source-agnostic tools, schema design, mapping, deterministic and LLM quality checks, bounded revision, combined human review, approval, lineage, drift, and LangGraph nodes/state/checkpointing. The embedded JSON example parses successfully, code fences are balanced, trailing-whitespace checks pass, and `git diff --check` passes. No application tests were needed because this change only adds documentation.
