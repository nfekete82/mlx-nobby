# DFlash2 Quality A/B for Qwen3.8 Abliterated (manual opt-in)

The first short latency probe measured only 2 output tokens. The follow-up
realistic decode probe measured Qwen3.8-27B-Abliterated-MLX-4bit at approximately
32.29 tokens/s (long explanation) and 30.41 tokens/s (coding) without DFlash2,
versus 38.62 and 48.63 tokens/s with the locally cached DFlash2. These are
historical, user-reported medians, not a general speed guarantee. The native
server was verified with --draft-kind dflash and --draft-model
z-lab/Qwen3.8-27B-DFlash2.

Faster generation is not enough: quality, actual formatting and correctness
must be checked under both configurations. This script provides a *small
objective sanity check* without executing generated programs.

## The suite

- 4 German instruction/reading questions
- 5 multistep logic/arithmetic/combinatorics questions
- 4 Python 3 code-reading questions
- 4 JavaScript code-reading questions
- 1 longer **ungraded** text completion for median tokens/s and elapsed time

Each graded task has one authored, exact canonical answer. The model must
respond as a strict JSON object with exactly one string property "answer".
Wrong, invalid or verbose answers count as failures, even if a human could
interpret them as correct. This is *format adherence + narrow correctness*,
NOT a general reasoning benchmark, autonomous coding assessment, software
quality score or safety evaluation. Python and JavaScript code is present
only in prompts; **the generated model output is never executed**.

Reports include case ID, category, repeat, correctness, end-to-end time,
provider generation rate, completion tokens and termination reason. Report
file permissions are 0600. Raw model answers and prompts are never persisted.
No model, service, config, job, cache or safety-limit changes are made by
the Python runner.

## Run ON first (current Qwen3.8 + DFlash2)

Run only when chat/image/video jobs are idle and nobody is using Nobby.
Execute from the checkout containing the script (or after the PR merge
from ~/mlx-web). You must **manually restore the starting configuration**.

    cd ~/mlx-web
    source "$HOME/.config/mlx-server/config"
    python3 scripts/benchmark-dflash-quality.py run \
      --mode on --model "$MODEL" --repeats 2 \
      --output /tmp/nobby-dflash-quality-on.json

If the script refuses to run, verify the process args:

    ps -axo command | grep '[m]lx_vlm server'

The ON test demands exactly one matching local model server on port 8000
with --draft-model z-lab/Qwen3.8-27B-DFlash2 and --draft-kind dflash.
It will not silently run an ordinary no-draft target.

## Temporarily test OFF

The following operations intentionally change your local MLX runtime and
interrupt current chat requests. They are explicit commands: **only perform
them at an idle time**, and restore ON afterward.

    cd ~/mlx-web
    bash scripts/configure-qwen38-speculative disable
    ./scripts/mlx restart
    source "$HOME/.config/mlx-server/config"
    python3 scripts/benchmark-dflash-quality.py run \
      --mode off --model "$MODEL" --repeats 2 \
      --output /tmp/nobby-dflash-quality-off.json

IMPORTANT: If the OFF run fails, still restore your original ON runtime:

    cd ~/mlx-web
    bash scripts/configure-qwen38-speculative enable
    ./scripts/mlx restart
    bash scripts/configure-qwen38-speculative status
    ps -axo command | grep '[m]lx_vlm server'

**Never** leave a runtime changed as a side effect of benchmark troubleshooting.

## Compare (fully offline, no inference, no restart)

    cd ~/mlx-web
    python3 scripts/benchmark-dflash-quality.py compare \
      --off /tmp/nobby-dflash-quality-off.json \
      --on /tmp/nobby-dflash-quality-on.json

The comparison checks suite SHA-256, exact same model, repeat count, required
cases, verified ON/OFF modes and regressions per case. A candidate requires
no case that was previously correct to become incorrect, an overall quality
score at least as good as OFF, and >=10% median TPS gain on the long probe.
Even this result is **only a candidate for broader review**.

Tiny suites cannot guarantee language quality. Because outputs are not saved,
a separate human review of representative long answers and full generated
programs with isolated sandbox testing is necessary before declaring
coding-output quality unchanged. Thermal state and nondeterministic sampling
can distort small A/B runs. The script does not compute draft acceptance rate
or prove bitwise decoding identity.

Existing global 90% memory gating, 20 GiB reserve and media coordination
are untouched. Do not run OFF/ON jobs while heavy media generation is active.

## Offline tests

    python -m pytest -q tests/test_dflash_quality_ab.py

No inference, network or Mac process changes occur in these unit tests.
