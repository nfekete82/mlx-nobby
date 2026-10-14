# DFlash2 v2: extended A/B suite (opt-in)

This is a **new** comparison with its own suite SHA and schema. The v1 suite and
historical reports remain unchanged and are **not** directly comparable to v2.

## What it measures

- All 17 frozen v1 German/reasoning/Python/JavaScript questions.
- 8 additional PHP, JavaScript, Python, and SQL practical code-review
  multiple-choice questions with exact answers.
- Separate rates for **strict JSON correctness**, **exact substantive answer**
  even if formatting differs, and **format adherence**.
- Three ungraded generation probes: German long explanation (1024 tokens),
  PHP application code (1536), and JavaScript browser code (1536).
- Up to **10 independent repetitions per mode**. Default 3 for a quicker check.
- Paired relative TPS changes for outputs with comparable completion lengths.
  Pairs with fewer than 128 tokens, >15% difference in completion length, or
  missing native server timing are not used for speed comparisons.
- Negative and zero gains are included. At least 2 comparable profiles and
  >=10% median speed gain are necessary for a **review candidate**, as well as
  non-regressing strict/content scores. This is not automatic approval.

The score for PHP/JS/Python/SQL is **static comprehension and review**, not
proof that generated code works. Long-form example code is **never executed**
and never judged correct by the runner. Inspect it separately before deployment.
Generated prompts, raw model answers, and generated code are **not written**
to the result JSON. Reports are written exclusively with 0600 permissions.

## Diagnose the four repeated v1 failures

The v1 runner discards raw answers, so the existing report alone cannot show
whether reason-profit, py-slice, js-loop, and js-var failed for a factual
reason or merely because of strict JSON formatting. On a verified ON runtime:

    cd ~/mlx-web-dflash-ab
    git fetch origin
    git switch --detach origin/perf/dflash-quality-ab-v2
    source "$HOME/.config/mlx-server/config"
    python3 scripts/benchmark-dflash-extended.py diagnose \
      --mode on --model "$MODEL"

This prints the actual response only for those four public test questions
to the local terminal; it does not save it to the report. Use the output to
distinguish model errors from JSON-format errors. No runtime is restarted or
reconfigured. A diagnosis performed only in ON mode does not prove OFF behavior.

## Extended A/B run — leave production ON afterward

Make sure no chat, image, speech, or video generation is active. This example
intentionally restarts the runtime for the OFF phase and uses an EXIT trap to
restore ON even if a test or comparison fails. It assumes the initial runtime
is ON, as in the previous A/B run. It does not modify safety gates.

    bash <<'SH'
    set -euo pipefail
    WORK="$HOME/mlx-web-dflash-ab"
    RUNTIME="$HOME/mlx-web"
    cd "$WORK"
    git fetch origin
    git switch --detach origin/perf/dflash-quality-ab-v2
    source "$HOME/.config/mlx-server/config"
    OUT="$(mktemp -d /tmp/nobby-dflash-v2.XXXXXX)"

    restore() {
      cd "$RUNTIME"
      bash scripts/configure-qwen38-speculative enable
      ./scripts/mlx restart
    }
    trap restore EXIT

    cd "$WORK"
    python3 scripts/benchmark-dflash-extended.py run \
      --mode on --model "$MODEL" --repeats 10 \
      --output "$OUT/on.json"

    cd "$RUNTIME"
    bash scripts/configure-qwen38-speculative disable
    ./scripts/mlx restart

    cd "$WORK"
    python3 scripts/benchmark-dflash-extended.py run \
      --mode off --model "$MODEL" --repeats 10 \
      --output "$OUT/off.json"

    python3 scripts/benchmark-dflash-extended.py compare \
      --off "$OUT/off.json" --on "$OUT/on.json"
    echo "Local results: $OUT"
    SH

The run is deliberately opt-in and has many inference requests. To sanity
check first, use --repeats 1 in both phases; later use --repeats 10.
Do not use the benchmark from two terminals concurrently. Results are local
and excluded from git; never commit environment-specific JSON.

## Offline unit tests

    python3 -m pytest -q tests/test_dflash_quality_ab.py tests/test_dflash_extended.py

Tests do not contact the model or modify MLX. The diagnose subcommand is
different from normal benchmark mode because it explicitly prints public test
answers to terminal; that data is not captured in benchmark JSON.

## Limitations

Repeated identical questions can be biased by memorization or benchmark
specificity. Static multiple-choice tasks are not real software integration
tests; real coding quality still needs a reviewed program, isolated execution
and targeted unit/integration testing. No TTFT, speculative acceptance ratio,
prefill speed, RAM peak, swap, or thermal state are established by this suite.
No result alone establishes general equivalence of the abliterated target and
the DFlash2 draft, and no result changes the active MLX configuration.
