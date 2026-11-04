# Safe local MLX Nobby maintenance

An opt-in, host-only maintenance tool for **generated test data**. It does not
run in Docker or the inference process and never needs model access.

## Existing log rotation

Agent stdout/stderr already rotate in `agent/log_rotation.py`:
16 MiB per file and three numbered generations for each of `agent.log`
and `agent-error.log`. These are already bounded. Oversized pre-existing
logs are kept as `*.legacy-<timestamp>`, deliberately outside that
retention. This change does not replace or interfere with the writer.

## Preview what would be cleaned

From the local repository, without altering anything:

```sh
cd ~/mlx-web
python3 scripts/maintenance.py scan
python3 scripts/maintenance.py previews
```

The only automatically eligible generated artifacts are:

- `artifacts/ltx-quality-YYYYMMDD/`
- `artifacts/ltx-quality-causes-YYYYMMDD/`
- `artifacts/acceptance/acceptance-*/`

All must be **at least 14 days old based on their newest nested modification
time** (minimum configurable age: seven days). A symlink, a mount on another device,
an unexpected filesystem entry or a `.keep` / `.nobby-keep` marker prevents
the directory being deleted. Other artifact names remain untouched.
The scan includes sizes but does not read prompt contents.

## Explicit cleanup

After inspecting the dry-run output:

```sh
python3 scripts/maintenance.py clean --apply --yes
```

A manual *optional* legacy log cleanup can be reviewed with:

```sh
python3 scripts/maintenance.py scan --include-legacy-logs
```

Only legacy Agent files matching the exact naming pattern and older than
**30 days** are eligible. To remove them intentionally, run:

```sh
python3 scripts/maintenance.py clean --include-legacy-logs --apply --yes
```

An old log still open according to `lsof`, or an unavailable `lsof`,
prevents removal. The live Agent logs are never considered. If you need to
retain specific test diagnostics, create `.nobby-keep` inside that directory.

**Never covered:** local model stores, chat history, memory DB, knowledge,
RAG, media library, generated user media, persistent volumes, backups,
recently modified artifacts, unknown artifacts and Git repositories.

## Optional daily cleanup (macOS launchd)

Nothing is scheduled automatically when the PR is merged or the ordinary
installer runs. Install the dedicated LaunchAgent explicitly:

```sh
cd ~/mlx-web
python3 scripts/maintenance-launchagent.py install
python3 scripts/maintenance-launchagent.py status
```

It runs daily at **04:30 local time**, cleaning only the strict artifact
allowlist with a 14-day age threshold. It never enables legacy log removal,
Docker removal or Git worktree removal. It writes no unbounded scheduler log.

Disable scheduling without deleting data:

```sh
python3 scripts/maintenance-launchagent.py remove
```

## Preview management

```sh
python3 scripts/maintenance.py previews
```

This read-only inventory lists Docker Compose projects named
`mlx-pr<digits>-preview` and Git worktrees, marking worktrees that contain
uncommitted changes. There is **no automatic preview or worktree cleanup**.

For an individually reviewed Docker Compose PR preview, run:

```sh
python3 scripts/maintenance.py remove-preview --name mlx-pr417-preview
python3 scripts/maintenance.py remove-preview --name mlx-pr417-preview --apply --yes
```

Removal rejects other Compose project names, named/anonymous Docker
volumes and bind mounts outside the preview's Compose working directory.
It only removes exactly identified containers, not their files, host
folders, images or volumes. This is a destructive operation for the
container's **ephemeral internal state**; review it first. Worktree
removal stays manual, through `git worktree remove <path>` after checking
the branch and worktree status.

## Verification

```sh
python3 -m pytest -q tests/test_maintenance.py tests/test_maintenance_launchagent.py tests/test_log_rotation.py
python3 -m py_compile scripts/maintenance.py scripts/maintenance-launchagent.py
python3 scripts/maintenance.py scan
```

Do not replace comprehensive release, browser or local runtime acceptance
with these focused tests. For macOS operation, verify the launchd job state
and observe a real 14-day-old synthetic directory before enabling automation
on a production installation.
