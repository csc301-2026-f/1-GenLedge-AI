# Figma UI Adaptation Specification

## Purpose and status

This specification records how the current Figma Make prototype is organized in the React application and how its screens fit the agreed Flask modular-monolith architecture. It is a guide for connecting the prototype to real backend behavior later.

The current UI remains a prototype: workflow data is mocked and the frontend does not call Flask. Preserve the visual design and user-visible flow when replacing the mock behavior.

## Frontend organization

The Vite project lives in `src/frontend/`. `src/frontend/src/App.tsx` owns top-level screen selection and workflow gating. Screen components live under `src/frontend/src/features/`, while reusable controls and the app shell live under `src/frontend/src/shared/`. The Flask application lives separately under `src/backend/`.

| Location | Responsibility |
|---|---|
| `src/frontend/src/App.tsx`, `src/frontend/src/app/types.ts` | Select the active screen, track workflow completion, and pass navigation callbacks. |
| `src/frontend/src/features/auth/` | Sign-in screen. |
| `src/frontend/src/features/sources/` | Source list, database connection form, file-upload presentation, and source fixtures. |
| `src/frontend/src/features/discovery/` | Source selection and schema field discovery. |
| `src/frontend/src/features/mappings/` | AI routing review and mapping editor. |
| `src/frontend/src/features/runs/` | Run progress, pipeline schedule presentation, and run history. |
| `src/frontend/src/features/settings/` | Display preferences. |
| `src/frontend/src/shared/` | Buttons, inputs, tables, alerts, status tags, dialogs, navigation, and top bar. |
| `src/frontend/src/index.css` | Global theme tokens, typography, responsive sizing, and appearance settings. |

## Screen and backend mapping

| UI screen | D1 story | Backend capability | UI responsibilities |
|---|---|---|---|
| Sign In | US1 | `auth` | Collect credentials, show pending/error/success states, and establish the authenticated session. |
| Data Sources | US2 | `sources` | List sources; start file upload or database connection; open schema discovery for a source. |
| Schema Discovery | US3 | `sources` | Select a source, browse collections and discovered fields, filter results, and request a resample. |
| AI Routing Results | US4 | `mappings` | Review proposed target tables, accept or reject proposals, and proceed to field mapping. |
| Mapping Studio | US5 | `mappings`, `pipelines` | Edit, add, or remove mappings; review transformations; save and approve a mapping version. |
| Transform & Load | US6 | `runs` | Start a run, display its identifier and progress, and summarize extraction, load, and error results. |
| Pipelines & Run Monitor | US7 | `pipelines`, `runs` | View schedules and run history, update a schedule, and inspect execution status or failure details. |

The shared top bar, sidebar, and display preferences remain frontend concerns. Organization-scoped authorization is enforced by the backend for protected data; hiding or locking a sidebar item is only a navigation aid.

## User flow and interaction contract

1. Sign-in opens the source list after authentication.
2. Selecting a source advances to discovery. The user can inspect collections and fields, then request AI routing.
3. The user reviews target-table proposals, then reviews and edits field mappings before approval.
4. Approval enables a manual run. The API should return a run ID promptly; the UI displays progress and later results by reading run status.
5. The monitor screen lists pipelines and run history. Scheduled and manual executions use the same backend run behavior.

The sidebar may mark earlier workflow steps complete and keep later steps locked until prerequisites are complete. Preserve the current user flow unless product requirements change; backend state, not only frontend navigation state, must determine whether a mapping is approved or a run is allowed.

## Prototype behavior to replace

- Sign-in currently accepts any non-empty email after a short delay. Password, remember-me, and role are presentation-only; there is no authentication session.
- Source rows and source counts are fixed fixtures. The connection form and upload dialog do not create a source or transfer a file.
- Discovery fields and sample values are fixed fixtures. Resampling only shows a temporary loading state.
- Routing proposals are static. Accept/reject decisions are local component state and are not saved.
- Mapping edits are local state. The mapping assistant returns a demonstration message rather than invoking LangGraph.
- Run progress is simulated with timers and fixed result counts; no worker or warehouse is called.
- Pipeline schedules and run history are fixtures. Schedule changes and run actions are not persisted or executed.
- Display preferences are the exception: scale, font size, and theme are applied in the browser and saved to `localStorage`.

When implementing backend integration, replace fixture reads and simulated actions within the corresponding feature. Keep screen components responsible for presentation and interaction; use small feature-level API functions or hooks to call Flask rather than putting network logic into shared controls.

## Backend integration boundaries

- The frontend calls a documented Flask JSON API. Keep API request and response types aligned with the backend contract; generate or validate TypeScript types from the API schema when that schema is established.
- Source and schema data belongs to `sources`; AI mapping proposals, validation, edits, and approvals belong to `mappings`; pipeline definitions and schedules belong to `pipelines`; run creation and status belong to `runs`.
- Store an approved mapping as a version. A run must reference the approved version it executes so later edits do not silently change an in-progress or historical run.
- Start manual and scheduled work through the same run lifecycle. Return a run ID and let the UI refresh or poll for status instead of holding the initiating request open.
- Show actionable errors for upload, connection, discovery, mapping, and run failures. Do not expose credentials or raw sensitive records in screen state, errors, or logs.
- Keep source credentials and LLM credentials out of frontend code. Send only the schema metadata and limited samples needed for AI mapping; do not send full source records by default.
- Do not introduce frontend-specific behavior for AWS Glue. The UI interacts with run status while the backend chooses the Python worker or a future Glue executor.

## Visual adaptation and acceptance

- Keep the existing GenLedge visual language: navy application shell, light workspace, compact tables, status pills, familiar filter controls, and the existing color and spacing tokens.
- Preserve screen titles, labels, empty/error/loading affordances, and the multi-step workflow unless a product decision changes them.
- Shared controls stay visually consistent across all feature screens. Feature-specific content and mock fixtures remain in their feature folders.
- Before replacing a mock action, verify both its successful state and its pending/error state. Backend integration is accepted when each screen reflects persisted state returned by Flask and manual/scheduled runs converge on the same run-history view.
- Verify the complete path from sign-in through source selection, discovery, routing, mapping approval, run completion, and monitoring, along with direct navigation locking and display preferences.
