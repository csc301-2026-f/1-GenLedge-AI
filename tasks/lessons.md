# Lessons

- When creating a task branch, verify the requested base branch and fetch its latest remote state before creating or moving the branch. Do not assume the currently checked-out feature branch is the intended base.
- When integrating another contributor's published branch, preserve their original commits and authorship. Resolve conflicts in a separate commit; do not replace their work with a new single-author snapshot commit.
- When a user narrows a merge request to pushing a PR only, stop before merging or synchronizing dependent branches. Reconfirm the scope from their latest instruction and preserve the review step.
