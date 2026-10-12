# V15: cross-domain native live acceptance

This suite is a **new ten-question evaluation** rather than a variant of the
frozen 64-case passage-relative verifier benchmark or the Apple catalog
development fixture.

It tests product catalogs, release support, networking standards, general
health information, monetary policy, German legislation, NASA history,
German history, current Python releases, and a deliberately unverified
fictional product. The questions are fixed in
`tests/fixtures/v15_cross_domain_live.json`.

## Run locally on the Mac

Only after the native agent and SearXNG services are healthy:

```sh
cd ~/mlx-web
git pull --ff-only origin feat/v2-live-intelligence
python -m pytest -q tests/test_v15_cross_domain.py
mlx agent restart

# Start with three new prompts, each one collected independently.
python -m agent.v15_cross_domain run --limit 3

# Then run all ten questions; writes to a different timestamped directory.
python -m agent.v15_cross_domain run
```

Each invocation prints the output directory. `capture.jsonl` contains
the raw source provenance, answers, source-relative verifier decisions,
and content-free model-call performance events.
`technical_summary.json` contains transport, source count,
model-call count and timings per case plus median and nearest-rank P95.
`human_review.csv` is intentionally **blank**: no program can
honestly fill it from supported-count or transport-success alone.

The output directory defaults to
`artifacts/performance/v15-cross-domain-<UTC timestamp>`.
It is Git-ignored and created with exclusive semantics to preserve previous
runs. The script only sends its fixed, public test questions to the
user-specified **loopback** HTTP agent endpoint. It does not change settings
or touch other Docker projects. It performs each question once without
retrying until a success appears.

## Performance interpretation

The reporter groups actual `provider.complete` events by purpose
(e.g. agent.plan, agent.extract, agent.verify). `model_ms_total` captures
their measured time. `unattributed_ms` is only the difference between
the end-to-end request time and recorded model time; it may contain search,
network, scheduling, CPU and other overhead. **Do not infer that it is all
web search time.** For small sample sizes the P95 nearest rank often equals
the slowest observation.

No fabricated before/after metrics, quality labels, performance wins or
ground-truth statuses are included.

## Read-only investigation of zero-supported captures

If a smoke run finishes with zero supported facts, **do not repeat all
questions or count completed as a quality pass**. Inspect the existing
capture before editing prompts or changing the model:

```sh
python -m agent.v15_run_inspection --run-dir artifacts/performance/REPLACE_WITH_ACTUAL_RUN
```

The inspector prints each original question, search providers and status,
first result domains/paths, successful fetches and text lengths, evidence
error/claim decisions, recorded model-call time by purpose, and the final
answer. It does **not** call the native agent or the internet, read extra
sources, print complete fetched web documents, or infer accuracy.

The stage_hint labels are preliminary triage buckets, **not confirmed root
causes**. A zero-supported result might be an appropriate refusal, and
the cited-source or factual-quality judgment still requires independent
review. The existing capture.jsonl is never overwritten.
## Mandatory human review

For each returned answer, open `capture.jsonl` and fill all
five dimensions in `human_review.csv` using **0, 1 or 2**:

| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| relevance | Off topic | Partly addresses user intent | Directly answers intent |
| accuracy | Material error or fabricated claim | Uncertain/mixed, needs checking | Claims independently cross-checked against current reliable sources |
| completeness | Important requested aspect missing | Material but partial answer, openly scoped | All requested aspects covered, or justified uncertainty for negative control |
| citations | No usable links / fake links | Some valid links but insufficient grounding | Applicable individual claims backed by relevant loaded sources |
| safe_uncertainty | Fabricates certainty | Some limitations hidden | Accurately scopes uncertainty and does not invent unsupported existence or sale status |

The final dimension matters especially for the **Asterium Cloudphone Q-98765** negative
control: failure to establish existence does not prove it does not exist. An
honest source-limited refusal can receive a good review.

To generate the manually reviewed summary:

```sh
python -m agent.v15_cross_domain score --run-dir artifacts/performance/REPLACE_WITH_ACTUAL_RUN
```

**Only** human review fills the accuracy/relevance metrics. An individual
`supported` label proves merely that the model decided the
claim was entailed by an exact fetched passage; it is not third-party factual
verification. The JSON flag `fully_acceptable` is deliberately
strict: only if every attempted case has all dimensions scored 2.

If technical calls fail or fewer than ten questions are run, describe those
limitations. Do not report a three-question smoke test as full release
acceptance or turn this suite into train-on-test prompts.

## Release decision

Keep PR #202 unmerged until:

- macOS unit/integration and browser CI are green;
- all ten **native** case outputs are captured and independently reviewed;
- the broad study shows source accuracy and relevance, not merely `supported_count > 0`;
- repeated latency outliers are investigated by model purpose and search/fetch path;
- existing frozen semantic verifier results do not regress.

Source-relative 64/64 and one Apple catalog success are valuable but do not
satisfy the cross-domain production release gate on their own.
