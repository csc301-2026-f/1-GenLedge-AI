# US3 discovery presentation plan

## Scope

Replace the working frontend's hardcoded discovery screen with a typed presentation component for discovery contract v1. A separate synthetic preview host supplies generated fixtures until authorized source reading and HTTP contracts are available. Preserve the original Frontend Demo and other workflow screens.

## Success criteria

- Render canonical paths, all observed types, nullable/repeating flags and JSON scalar samples.
- Search paths and filter observed types and change status.
- Display added, missing and changed types; explain sampling absence without claiming deletion.
- Accept controlled loading, error and ready states; show empty and no-match messages.
- Delegate resampling to the caller; no timer or fake persistence in the presentation component.
- Build and typecheck the frontend, inspect the diff, document integration boundaries.

## Sequence

- [x] Inspect instructions, existing discovery screen, app host and Python output contract.
- [x] Implement typed presentation and separate synthetic preview.
- [x] Verify build/typecheck and fixture consistency; update smoke documentation.
- [x] Finalize plan and commit the focused UI feature.

## Verification and remaining integration

- Frontend TypeScript check (`node_modules/.bin/tsc --noEmit`) and production build (`node_modules/.bin/vite build`) passed.
- Preview payloads were generated directly from the existing Python discovery/comparison functions and synthetic fixtures, without a database or HTTP request.
- Reviewed controlled state branches, disabled actions, path keys, filter labels and sample rendering using the React best-practices checklist.
- Diff whitespace check passed. No dependency/lockfile, auth, source screen, backend, README, original demo or historical deliverable changes.
- Browser/manual interaction checks are documented in `docs/smoke-tests.md` but were not executed in this task. No new automated tests were added or run.
- Real source/collection selection, authorized requests, validated responses, persisted snapshots and downstream mapping handoff remain separate integrations.
