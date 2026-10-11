# Frontend authentication ExecPlan

Backend handoff: commit 5c3306d pushed successfully; contract in doc/auth-api.md.

- [x] Inspect original frontend, auth UI, app state, shared top bar and adaptation spec.
- [x] Record original tracked SHA256 manifest in plans/frontend-demo-manifest.json; preserve demo and copy tracked files only.
- [x] Commit and push preservation independently.
- [x] Implement typed auth client and login/restore/logout state in new frontend.
- [x] Type check, build and exercise auth scenarios and static screens.
- [x] Recheck preserved demo hashes and diff; update documentation; commit and push.

Plan 3 owns Vite proxy and startup scripts; leave those files unchanged.

## Verification results

- Preservation commit: 17f3363, pushed before auth changes. All 24 original tracked file SHA256 hashes match the preserved demo, including PDF and lockfile. All working frontend files outside App.tsx, LoginScreen.tsx and shared/layout.tsx retain original baseline contents; client.ts and tests/auth-smoke.cjs are new auth-only files.
- `pnpm install --frozen-lockfile` succeeded with bundled Node/pnpm after sandbox network access failed; no lockfile or package changes. Unused install store was moved outside the checkout.
- From src/frontend: `pnpm exec tsc --noEmit` and `pnpm build` passed.
- Mocked browser acceptance passed in headless Chrome using Playwright: single initial me request under Strict Mode; required fields; API 400; network failures; keyboard and repeated submission; remember_me; refresh restore; expired session; logout failure retains user and permits retry; restore error retry; successful null/non-JSON error responses safely rejected. Static sources/discovery/routing/mapping/run/monitor navigation and display-settings rendering passed. Appearance screenshot inspected.
- Browser harness initially asserted a security header that Playwright omits from its abbreviated headers; removed that harness-only assumption and reran successfully.
- No fixture, non-auth screen, README, Vite config or startup-script changes. Existing untracked user HTML files preserved.

## Plan 3 handoff

Use src/frontend with pnpm. Auth client: src/frontend/src/features/auth/client.ts, using /api/auth relative URLs and credentials: include; contract remains doc/auth-api.md from backend commit 5c3306d. Demo preservation commit is 17f3363; auth commit is the commit containing this finalized plan (retrieve with git log -- plans/frontend-auth.md).

Configure the Vite /api proxy and launchers in src/frontend/vite.config.ts, src/start-app.sh and src/start-app.bat. Verify actual browser-to-Flask login, cookie attributes and 14-day remember-me, refresh restore, logout, expired/absent session, backend outage/restart and non-default backend port with the final scripts. Current browser checks mock responses; real backend HTTP lifecycle was independently verified in Plan 1. No claim of final proxy integration is made here.
