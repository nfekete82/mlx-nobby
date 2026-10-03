# Releasing MLX Nobby

This is the canonical release procedure. Replace `X.Y.Z` with the target product
version. See [Testing](TESTING.md) for test setup, capabilities and diagnostics,
and [Contributing](../CONTRIBUTING.md) for development conventions.

## Principles

- Start releases from a clean, synchronized `main`.
- Keep release preparation isolated from product development.
- Release PRs contain release metadata only.
- Product bugs found during preparation require a separate fix PR.
- Create release tags only after final-main acceptance and green CI.
- Never force-tag, overwrite a release, or replace an existing release tag.
- Acceptance must pass before publication.

## Git and attribution rules

Read and follow [AGENTS.md](../AGENTS.md) before release work; it is the source
of truth for repository Git rules. Use only the configured Git identity. Do not
add `Co-authored-by`. Do not add `Signed-off-by` or other attribution trailers
unless explicitly requested. These rules apply to every commit, including merge
commits.

Do not create or use stashes as release working storage. Record and preserve
pre-existing stashes exactly; do not apply, delete or add to them. Record the
state of unrelated worktrees and leave them untouched. Never force-push a
release tag or replace an existing tag.

## Release metadata

Before preparation, `CHANGELOG.md` collects changes under `## Unreleased`.
At release time, retain that heading and leave it empty; move its entries into
a new `## vX.Y.Z` section immediately below it. Follow the existing changelog
style and audit the actual range from the previous release tag to `main`:

```sh
git log --oneline --decorate vPREVIOUS..main
git log --merges --oneline vPREVIOUS..main
```

Set `VERSION` to `X.Y.Z`. Update other exact references only when they represent
the MLX Nobby product version, such as the README release badge and assertions
in `tests/test_version_routes.py`. Preserve historical changelog sections.
Do not change `/v1`, schema/API/cache/media versions, model versions or
dependency versions as part of a product version bump.

## Release branch

Read the repository instructions, then synchronize:

```sh
git switch main
git fetch origin --prune --tags
git pull --ff-only
git status
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git stash list
git worktree list
git tag --list 'vX.Y.Z'
```

Require branch `main`, `HEAD == origin/main` and a clean working tree. Stop on
unexpected changes; do not repair them with a stash or reset. The target tag
must not exist locally or remotely after fetching. Record stash object IDs and
unrelated worktree heads/status for final comparison.

```sh
git switch -c release/vX.Y.Z
```

The release PR may change release metadata only. Review `git status`, `git diff`
and `git diff --check`; exclude logs, generated media, test artifacts, local
configuration, secrets and product logic.

## Release gate

Run the canonical local gate on the release branch:

```sh
./scripts/mlx test-release
```

It runs Python unit/integration tests and subtests, JavaScript tests,
syntax/JSON/i18n/shell/plist checks, dependencies, Compose validation, Docker
build, docs/help checks, diff validation, deterministic Chromium browser
acceptance and local real-runtime acceptance. Each layer runs once.

Exit code **0** is required. Use the existing test environment, installed
Chromium and already running local services/models as described in
[Testing](TESTING.md). Acceptance never downloads/selects models, resets services
or cancels foreign jobs. Installed core capabilities must pass; optional missing
capabilities must have explicit, permitted SKIP reasons. Record actual test
counts, real check results and duration.

Run this gate on the reviewed metadata changes before committing them. Those
intentional edits on the release branch are expected; preflight and final `main`
must be clean, and unexpected changes always stop the release.

The default gate does not perform an expensive full Shorts render. `--full`
is an explicit opt-in supported by `test-release` and `test-real`; full Shorts
may SKIP in the normal release gate. Draft/read/preflight remain checked.

## Release pull request

Only after the local gate passes, commit and open the PR with the same title:

```text
chore(release): prepare vX.Y.Z
```

Describe the audited release range, metadata changes, actual test counts and
acceptance results. Before merge require a reviewed metadata-only diff, local
release gate PASS, green Standard Tests, Browser acceptance, Docker and all
required PR checks. Wait for checks on the final PR commit.

Stop for a reproducible test failure. A diagnosed, unchanged timing flake may
be rerun once; do not repeatedly rerun until green or ignore a failure to publish.
Product bugs require a separate fix PR, followed by fresh release preparation
from current `main`.

## Final-main acceptance

After merging the release PR:

```sh
git switch main
git fetch origin --prune
git pull --ff-only
git status
git rev-parse HEAD
git rev-parse origin/main
./scripts/mlx test-e2e
./scripts/mlx test-real
```

Require clean `main == origin/main`. Remove the merged release branch locally
and remotely, checking its merged identity before deletion. Both acceptance
commands must pass on this final merge commit; its required CI must also be
green. A core feature failure means **no tag and no release**.

Check `VERSION` and the `/api/version` contract using the current application
or a controlled TestClient against the current checkout. Both must report the
target product version; an older deployed application is not this check.

## Tagging

Recheck synchronized, clean final `main` and absence of the target tag. Only
after final-main acceptance and CI pass, create an annotated tag:

```sh
git tag -a vX.Y.Z -m "MLX Nobby vX.Y.Z"
git rev-parse HEAD
git rev-parse vX.Y.Z^{commit}
git rev-parse vX.Y.Z
```

`HEAD` and `vX.Y.Z^{commit}` must be exactly identical. An annotated tag has a
**tag object SHA** and a different **peeled commit SHA**; the peeled commit,
not the tag object, must equal final `main`. Record both. Never force-tag.

```sh
git push origin vX.Y.Z
```

Verify the remote annotated tag and its peeled commit before publication.

## GitHub Release

Create a published GitHub Release for the existing verified tag `vX.Y.Z`, named
`MLX Nobby vX.Y.Z`, with `draft=false` and `prerelease=false`.
Derive notes from the finalized changelog and actual release range. Do not
include local absolute paths, test-artifact paths or secrets in published notes.
Do not let release creation invent a tag or overwrite an existing release.

## Final verification

Fetch and fast-forward `main`, then verify:

- `main == origin/main == vX.Y.Z^{commit}` and the working tree is clean.
- `VERSION` is correct, `Unreleased` is present and empty, and `vX.Y.Z` exists
  in the changelog.
- The remote tag matches the verified local annotated tag and peeled commit.
- The GitHub Release is published with `draft=false` and `prerelease=false`.
- The release branch is removed locally and remotely.
- No new stashes exist; pre-existing stashes and unrelated worktrees are unchanged.

## Abort conditions

**STOP release work** if preflight/final-main is not clean, unexpected working
tree changes appear, `main != origin/main`,
the target tag already exists, the release gate/browser/real acceptance or
required CI fails, a product bug is found, release preparation would require
product logic changes, or the final tag target does not exactly equal `main`.
Do not tag or publish while a critical step is failed. Report the exact blocker.

For product errors, use a separate fix PR. After that PR is green and merged,
restart release preparation from current synchronized `main` and repeat gates.
Never replace a tag or overwrite a published release to repair a mistake.

## Release checklist

- [ ] AGENTS.md read and followed
- [ ] No attribution trailers
- [ ] Main clean and synchronized
- [ ] Target tag does not exist
- [ ] Release range audited
- [ ] VERSION updated
- [ ] CHANGELOG finalized
- [ ] Unreleased empty
- [ ] Release diff contains metadata only
- [ ] `./scripts/mlx test-release` PASS
- [ ] Release PR CI green
- [ ] Release PR merged
- [ ] Final-main `test-e2e` PASS
- [ ] Final-main `test-real` PASS
- [ ] Final-main required CI green
- [ ] Version endpoint reports target version
- [ ] Annotated tag targets final main
- [ ] Tag pushed and remote target verified
- [ ] GitHub Release published
- [ ] draft=false
- [ ] prerelease=false
- [ ] Release branch removed
- [ ] Working tree clean
- [ ] No new stashes; pre-existing stashes unchanged
- [ ] Unrelated worktrees unchanged
