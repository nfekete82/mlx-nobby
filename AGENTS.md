# Repository instructions

## Git commit attribution

- Do not add `Co-authored-by` trailers to commit messages.
- Do not add `Signed-off-by` or other attribution trailers unless explicitly requested.
- Use only the repository's configured Git author identity for commits.

## Image model test records

- Update `docs/image-model-test-matrix.md` after every image model test, including
  failed attempts and regressions. Record the exact model/checkpoint, architecture
  and provider, installation state, actual test date, GPU/load result, render time,
  resolution, steps, CFG, scheduler, seed, observed quality, known issues and the
  decision to retain, retest or reject. Link supporting evidence where available.
- A model may be marked `tested` only after at least one successful real image
  generation. Registry/profile tests, installation and successful loading alone
  do not qualify; keep unrendered integrations `configured` or `planned`.
