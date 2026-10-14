# DFlash2 v3: executable coding A/B (explicit local opt-in)

This is **separate from** DFlash2 v1/v2. Those suites remain frozen. The v2
speed/strict-JSON results do not measure whether a generated application works.

## New comparison

Nine small, public **code-generation** prompts in Python 3.12, JavaScript
(Node 22), PHP 8.3. The code is run against additional deterministic assertions,
including the four concepts that previously produced wrong answers:

- Python string-slice reverse and an accounting/profit calculation
- JavaScript even-number loop and closure behavior
- Python stock allocation / cent-safe invoice sums
- JavaScript cent-safe cart aggregation
- PHP discounted total in integer cents and SKU normalization

Per mode: nine prompts x number of repeats (1..5). Reports contain only case IDs,
boolean pass/fail, response formatting class, token counts, timing and whether
the generation token cap was reached. **No generated code, prompts, container
stdout, stderr or raw model responses are persisted.**

Generated source is never executed by the Python benchmark process. Docker
gets generated source plus hidden assertions **through stdin only**, using
images already cached locally. The runner makes no pulls and does not mount
local directories or files into the container. Runtime changes are not made
by the runner.

### Docker isolation (not a perfect security boundary)

The runner launches Docker containers with network disabled, read-only root
filesystem, no additional Linux capabilities, no-new-privileges, nonroot user,
limited CPU, RAM, process count, file descriptors and execution timeout.
Default Docker seccomp and image configuration apply. The model may emit
incorrect, looping or malicious code; containers reduce risk, but do not
provide a formal guarantee of isolation. Run on an idle machine with an up-to-date
Docker Desktop installation.

Required locally cached images:

- python:3.12-alpine
- node:22-alpine
- php:8.3-cli-alpine

You can deliberately preload missing images, if desired:

    docker pull python:3.12-alpine
    docker pull node:22-alpine
    docker pull php:8.3-cli-alpine

This is a manual user action, **not** part of the benchmark. Running the
benchmark with absent images fails closed before any model call. The test
harness never falls back to executing model-generated code on macOS.

## Local smoke test and offline unit checks

    cd ~/mlx-web-dflash-ab
    git fetch origin
    git switch --detach origin/perf/dflash-quality-ab-v2

    python3 -m pytest -q \
      tests/test_dflash_quality_ab.py \
      tests/test_dflash_extended.py \
      tests/test_dflash_code_exec.py

    docker info
    docker image inspect python:3.12-alpine node:22-alpine php:8.3-cli-alpine

Ensure the already running model has DFlash2 ON before the next run.

## Safe A/B (ONE repetition initially)

The runtime toggles interrupt current model requests. Avoid concurrent
chats, media jobs, benchmark terminals, or heavy memory loads. This command
starts with the known ON configuration. A shell EXIT trap restores ON even on
normal command failure; a hard crash/power loss can prevent cleanup.

    bash <<'SH'
    set -euo pipefail

    WORK="$HOME/mlx-web-dflash-ab"
    RUNTIME="$HOME/mlx-web"
    source "$HOME/.config/mlx-server/config"
    OUT="$(mktemp -d /tmp/nobby-dflash-code.XXXXXX)"

    restore() {
      cd "$RUNTIME"
      bash scripts/configure-qwen38-speculative enable
      ./scripts/mlx restart
    }
    trap restore EXIT

    cd "$WORK"
    python3 scripts/benchmark-dflash-code-exec.py run \
      --mode on --model "$MODEL" --repeats 1 \
      --output "$OUT/on.json"

    cd "$RUNTIME"
    bash scripts/configure-qwen38-speculative disable
    ./scripts/mlx restart

    cd "$WORK"
    python3 scripts/benchmark-dflash-code-exec.py run \
      --mode off --model "$MODEL" --repeats 1 \
      --output "$OUT/off.json"

    python3 scripts/benchmark-dflash-code-exec.py compare \
      --off "$OUT/off.json" --on "$OUT/on.json"

    echo "Local report directory: $OUT"
    SH

For greater confidence after inspecting the smoke-test result, use
--repeats 3 **on both run commands**, with a new output directory. Do not
reuse JSON report paths: writes are exclusive and files are permission 0600.

The benchmark never installs dependencies, selects models, changes memory
limits, or automatically approves DFlash2. The accompanying comparison reports
case-level regressions/new passes; it **does not** imply application-wide
correctness, security, or source-code quality.

## Offline validation

    python3 -m pytest -q tests/test_dflash_code_exec.py

Unit tests use mocked HTTP/Docker APIs and cannot reach the model or execute
generated source. Real Docker evaluation requires explicit local invocation.

## Limitations

Static unit tests do not prove an application is secure, stable, well-designed
or idiomatic. Extra commentary, truncated code, different function names and
unhandled formatting can fail despite some useful source text. The evaluator
records this as a failed runnable program, which is appropriate for automated
deployment criteria but not a holistic coding-capability score. A few
single-purpose programs do not establish general model parity; temperature 0
does not guarantee deterministic results. All comparisons should consider
paired regression counts, not just one aggregate score. If Docker fails during
execution the benchmark aborts instead of silently treating infrastructure
failure as a model defect.
