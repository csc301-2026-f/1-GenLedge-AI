# Lessons

- API guides should list every implemented endpoint explicitly, including helper
  endpoints such as CSRF token retrieval, and distinguish HTTP routes from internal
  interfaces and future endpoints.

- When creating a task branch, verify the requested base branch and fetch its latest remote state before creating or moving the branch. Do not assume the currently checked-out feature branch is the intended base.
- When a user narrows a merge request to pushing a PR only, stop before merging or synchronizing dependent branches. Reconfirm the scope from their latest instruction and preserve the review step.
- Before implementing a user's independently owned story, check whether the current feature branch belongs to a teammate and whether its APIs are unfinished. Keep integration at a narrow boundary and use the agreed base branch instead of implicitly depending on a teammate's work in progress.
