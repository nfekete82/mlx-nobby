# Hybrid: Long-form quality and memory acceptance (opt-in)

This supplements the short two-turn codeword check in PR #276. **It is not
an automatic production benchmark or proof of numerical equivalence.**
The default runtime remains DFlash2.

The synthetic acceptance test checks:

- A 4k or 8k nominal context containing three invented canary markers
- A second question requiring those markers and a detailed explanation of
  Prefill, Decoding and Streaming (at least 400 generated characters)
- A real APC exact-cache hit in the experimental hybrid profile
- Normal memory pressure and at least 6 GB headroom before, 5 GB after
- No more than 1 GB observed swap growth during each profile's workload
- Advisory text-similarity ratio between DFlash2 and Hybrid (not a pass/fail gate)
- Restoration of the original chat profile on errors/interrupts where possible

Prompts and model responses are held in RAM only. The JSON report includes
timings, lengths, booleans, similarity ratio and before/after memory snapshots;
**no full prompts or generated text are persisted or printed**. The existing
stream helper retains the first 2048 visible characters for in-memory
inspection, so canaries are checked in that captured prefix.

## Run manually on an idle Mac after GitHub CI is green

```bash
cd ~/mlx-web
git fetch origin
git switch --track origin/test/hybrid-longform-parity-memory

./test-venv/bin/python -m pytest -q \
  tests/test_validate_hybrid_longform.py \
  tests/test_validate_hybrid_correctness.py \
  tests/test_hybrid_apc_dflash_runtime.py

python3 scripts/validate-hybrid-longform.py \
  --context-size 4000 \
  --min-characters 400 \
  --timeout 300

./scripts/mlx chat-profile status
./scripts/mlx memory
```

The test runs **DFlash2 followed by Hybrid**, restarts the model server as
needed and attempts to restore the initial profile. Review answer checks,
exact-hit counts, swap growth, memory headroom and content-similarity ratio.

Passing this smoke test does **not** establish long-term output correctness,
memory-peak safety or concurrent media stability. Keep the Hybrid opt-in
until repeated Apple-Silicon soak tests and longer-answer comparisons pass.

## Limitations

- Before/after snapshots can miss short-lived GPU memory spikes.
- Answer similarity is advisory because wording can differ between modes.
- The context-size number is heuristic, not tokenizer-accurate.
- If a check fails, don't blindly re-run: inspect the error and final profile.

## First live hardware test: both profiles failed strict three-marker recall

On the user's M5 Max, the first test of this branch returned `passed=false`
in both DFlash2 and Hybrid: technical keywords were present, output was long
enough, and Hybrid registered a true APC exact hit. No individual marker
or generated content was included in the first report, so it was **not**
possible to distinguish absent markers from differently formatted words.

The initial follow-up wording ("without guessing") also permitted an
unhelpful interpretation that the model should avoid supplying the words.
The follow-up now specifies a required first-line format **without including
the actual synthetic marker values**. Strict recall is still required.

New output field `synthetic_marker_diagnostics` contains, for each of
the three artificial markers, a boolean for exact presence, separator/umlaut
normalized presence, and presence on the first nonempty answer line.
No response excerpt, private text or model output is saved.

Use these per-marker booleans to diagnose whether both models actually
fail memory retrieval or instead change spelling/format. Do **not** loosen
the passing criteria based on formatting alone. The previous low text
similarity (0.307) was advisory, not evidence by itself of a hybrid error.

The test still must be rerun on actual Apple Silicon hardware; GitHub
CI checks CPU-only contracts, not real model output quality.
