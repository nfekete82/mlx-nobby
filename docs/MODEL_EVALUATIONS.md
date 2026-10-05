# Model evaluation history

MLX Nobby keeps two different kinds of local model history:

- `~/.config/mlx-web/model-scout-benchmarks.json` contains the detailed raw Model Scout A/B benchmark reports.
- `~/.config/mlx-web/model-evaluations.json` contains durable decisions across model types so already-tested regressions are not treated as fresh upgrade candidates later.

The evaluation registry is intentionally local. Benchmark results depend on the Mac, quantization, target model, workload and runtime versions, so a result measured on one machine is not a global statement about a model.

## Status values

- `keep`: current winner / model worth retaining for this role.
- `rejected`: tested for this role and did not justify replacing the comparison model.
- `candidate`: promising result that deserves broader validation.
- `tested`: measured, but the result was mixed or inconclusive.
- `superseded`: historical choice that has intentionally been replaced.

Decisions are role-specific. The same model can be useful for one kind of work and rejected for another.

## Automatic recording

The ASR benchmark records its winner as `keep` and the alternatives as `rejected` by default. Use `--no-record-evaluations` when a temporary experiment should not affect the registry.

Model Scout quick A/B benchmarks also record their result:

- `strong_candidate` / `promising` -> `candidate`
- `quality_regression` -> `rejected`
- `mixed` -> `tested`

Model Scout discovery attaches the latest matching evaluation to each candidate. A locally rejected Chat, Coding or Vision model receives discovery status `rejected` and score `0`, keeping the evidence visible without recommending it again as a fresh upgrade.

## CLI

List the latest decision for each model and role:

```sh
python3 scripts/model-evaluation.py list
```

Only rejected models:

```sh
python3 scripts/model-evaluation.py list --status rejected
```

Inspect one model:

```sh
python3 scripts/model-evaluation.py show \
  --model mlx-community/Qwen3-ASR-1.7B-6bit \
  --kind asr
```

Record a manual benchmark decision:

```sh
python3 scripts/model-evaluation.py record \
  --model owner/model \
  --kind chat \
  --status rejected \
  --compared-to owner/current-model \
  --reason "No measurable local advantage" \
  --source manual-benchmark \
  --metric generation_tps_delta_pct=-2.1
```

Each new record is appended to history. `list` and `show` use the most recent decision, so a later successful retest can replace a previous rejection without deleting the older evidence.

## API

The native Agent exposes:

- `GET /api/model-scout/evaluations`
- `POST /api/model-scout/evaluations`

The web backend proxies the same API under `/api/mlx/model-scout/evaluations`.
