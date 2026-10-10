# Repository Agent Instructions

These instructions apply to work in this repository. They are intended to be general and repository-agnostic; project-specific implementation details belong in the relevant source files and documentation.

## Precedence

Apply instructions in this order:

1. Explicit system, developer, and active-session user instructions.
2. This repository instruction file.
3. Shared or parent-level agent instructions.
4. Nested agent instructions, which may add stricter local requirements but may not relax higher-priority rules.
5. Optional local overrides, which may add stricter personal or machine-specific constraints but may not weaken repository rules.

When instructions conflict, follow the higher-priority instruction and surface material conflicts clearly.

## README Protection

- Never create, edit, reformat, rename, or delete a README file unless the user specifically requests a README change.
- This rule applies to every README file, including the root `README.md`.
- Do not run or follow a README synchronization workflow when it would modify a README without that explicit request. If another instruction or skill appears to require a README edit, this protection takes precedence unless the user specifically authorizes the README change.
- You may inspect README files when needed, but leave them unchanged and report any relevant staleness or conflict without fixing it.

## Planning and Execution

- For non-trivial work (three or more steps, multiple files, or an architectural decision), make a plan before implementation and maintain an ExecPlan at `plans/<task-slug>.md`.
- Keep the plan concrete and checkable. Update its status as work progresses and record verification results before finishing.
- When implementation is complete, save the finalized plan in `doc/` as part of the deliverable.
- For small tasks, use a brief inline plan when it helps keep the work clear.
- Break complex work into focused parts and combine the results before implementation. For non-trivial bugs, use subagents to investigate root causes or candidate fixes in parallel when the environment supports them.
- If investigation reveals a material contradiction or an unsafe assumption, pause implementation, state the conflict, and get clarification when the answer cannot be determined from the repository.

## Repository Workflow

- Read the relevant source, tests, documentation, and existing patterns before editing.
- Inspect the working tree and current branch before making changes. Preserve pre-existing user changes.
- Keep changes focused, minimal, and reversible. Avoid unrelated refactors and do not remove code or comments without understanding their purpose.
- Prefer existing project conventions and established helpers over new abstractions.
- When behavior changes, update relevant non-README documentation in the same change.
- When a change introduces or alters a concrete manual verification step, update the relevant smoke-test documentation if the repository has one.
- When a workflow creates commits, push the active branch after each successful commit unless the user explicitly says not to.

## Bugs and Tests

- For bug reports, first reproduce the issue with a failing test or another reliable executable reproducer. Do not implement a fix until the reproducer fails for the expected reason.
- If an automated reproducer is impractical, explain why and use the closest reliable alternative.
- For behavior changes, define success with focused tests where practical, then implement and run those tests.
- Run relevant tests, type checks, builds, and manual checks. Do not claim verification that was not performed.
- Before finishing, inspect the diff for regressions, unnecessary churn, and missed edge cases.
- After a user correction, record the reusable lesson in `tasks/lessons.md`, creating the file if needed.

## Code and Data Quality

- Prefer clear, explicit code that matches surrounding style. Avoid hypothetical features and premature abstractions.
- In typed code, use the project's designated types and checkers; avoid untyped public interfaces where practical.
- Validate persisted or external data at boundaries. Make schema changes resilient and report failures with actionable messages.
- Handle errors deliberately and preserve useful diagnostics. Keep modules focused and split files that have grown too large or span unrelated concerns when the task warrants it.
- Do not silently delete code that only appears unused. Call out likely dead code and ask before removing unrelated or uncertain code.

## Git and Delivery

- Keep commits focused and use Conventional Commit messages when a commit is requested or required by the task.
- Do not commit or push unless requested by the user or required by the active task instructions.
- Before delivery, summarize the changes, affected files, tests and checks run, and any remaining risks or limitations.

## Communication

- State assumptions when they materially affect the implementation.
- Explain problems directly, with concrete evidence where available.
- Do not claim work is complete until the implementation and relevant verification are complete.
