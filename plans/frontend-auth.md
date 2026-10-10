# Frontend authentication ExecPlan

Backend handoff: commit 5c3306d pushed successfully; contract in doc/auth-api.md.

- [x] Inspect original frontend, auth UI, app state, shared top bar and adaptation spec.
- [x] Record original tracked SHA256 manifest in plans/frontend-demo-manifest.json; preserve demo and copy tracked files only.
- [ ] Commit and push preservation independently.
- [ ] Implement typed auth client and login/restore/logout state in new frontend.
- [ ] Type check, build and exercise auth scenarios and static screens.
- [ ] Recheck preserved demo hashes and diff; update documentation; commit and push.

Plan 3 owns Vite proxy and startup scripts; leave those files unchanged.
