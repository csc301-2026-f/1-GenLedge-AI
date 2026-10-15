# Lessons

- Compare persisted JSON with JSON-aware equality: Python dictionary equality
  treats booleans as numbers (`True == 1`). Normalize requests with the same
  serialization used for storage, preserve boolean identity, and test replay
  conflicts separately from coverage percentages.

- When creating a task branch, verify the requested base branch and fetch its latest remote state before creating or moving the branch. Do not assume the currently checked-out feature branch is the intended base.
- When integrating another contributor's published branch, preserve their original commits and authorship. Resolve conflicts in a separate commit; do not replace their work with a new single-author snapshot commit.
- When a user narrows a merge request to pushing a PR only, stop before merging or synchronizing dependent branches. Reconfirm the scope from their latest instruction and preserve the review step.
