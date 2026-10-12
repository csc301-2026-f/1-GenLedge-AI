# Lessons

- When creating a task branch, verify the requested base branch and fetch its latest remote state before creating or moving the branch. Do not assume the currently checked-out feature branch is the intended base.
- Before implementing a user's independently owned story, check whether the current feature branch belongs to a teammate and whether its APIs are unfinished. Keep integration at a narrow boundary and use the agreed base branch instead of implicitly depending on a teammate's work in progress.
