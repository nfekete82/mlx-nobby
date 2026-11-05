# Memory reliability: partner correction passes the fixed replay

Date: 2026-11-05. Base: `f96d0b05` (PR #428). Development is an independent
Git checkout, not the production installation. No production chat, SQLite file,
memory setting, container, process or existing conflict was changed or reprocessed.

## Partner-only follow-up: deterministic validation correction

The separately authorized follow-up changes no prompt, acceptance input or recorded
model response. Exactly one replay of the existing `final.json` now passes:
**16/16 validated, persisted (including one real conflict) and retrieved with the
originating source; zero false conflicts or active values without literal support.**
Raw correctly assigned model extractions remain 14/16: the additional two targets
come from deterministic source normalization, not improved model output.

For an explicit, unquoted source clause starting with `Meine Partnerin heißt ...`
or `Mein Partner heißt ...` (also `heisst` / `trägt den Namen`), the existing regex
name extractor supplies the missing literal `partner.name`. An already grounded
`personen.<that-name>` candidate is remapped to `partner` only when its evidence
and value belong to that partner clause. A coordinated new subject ends the
eligible clause. A matching name elsewhere, a colleague or a friend is not enough.
The shared legacy name rule additionally accepts masculine `mein Partner`.

Both the synthesized name and remapped properties pass the existing literal,
confidence, privacy, negation, scope, conflict, source and deletion checks. There
is no production migration or change to existing stored memories.

The single live attempt stopped at the local model catalog probe because port
8011 refused the connection. **No inference ran**, no service was started and no
retry was made. Live-model confirmation of this follow-up is therefore unavailable.
Afterwards, **20 directly affected regression cases passed**, including source
provenance, masculine/feminine partner formulations, other named people, a colleague
with the same name in another clause, unsafe statements, confidence/grounding,
conflicts, pause and deletion guards. No general benchmark or suite was repeated.

Evidence: [partner replay and live-attempt record](memory-reliability-20261105/partner-replay.json).
The earlier three-round results below remain historical evidence, including the
previous identity regression. The original `final.json` is deliberately unchanged.

Limitations: the repair recognizes the narrow explicit naming forms above. It does
not infer partner identity from bare names, previous conversations, arbitrary
paraphrases or cross-sentence pronouns, and it does not invent omitted properties.

## Fixed acceptance set and measurements

Fourteen fictional messages contain sixteen expected information targets. The
script executes the real `process_message` path, durable job scheduling, existing
4B completion client, validation, `apply`, SQLite fact/conflict/episode persistence,
and lexical `knowledge_memory.context`. Each successful retrieval must contain
the expected value and its originating fictional chat/message in the same line.
The final answer generator is not invoked: these are answer-grounding measurements.
Embeddings are intentionally disabled in the isolated calling process.

Only three targeted rounds were run. Each round used the already running local
`Qwen3.5-4B-MLX-4bit` on port 8011, temperature 0, thinking disabled, with a fresh
temporary database. No model was launched. The 4B process and model identity were
verified before inference; the model catalog alone was not used as proof of load.

| Metric, out of 16 targets | Baseline | Round 2 | Final round 3 |
|---|---:|---:|---:|
| Correctly extracted and assigned, including episodes | 13 | 14 | 14 |
| Passed literal validation, including episodes | 13 | 13 | 14 |
| Persisted in facts/episodes or explicit conflict review | 13 | 13 | 14 |
| Retrieved with originating source | 12 | 13 | 14 |
| False conflicts | 0 | 0 | 0 |
| Real residence conflicts preserved | 1 | 1 | 1 |
| Active facts without literal source support | 0 | 0 | 0 |
| Hypothetical/question facts stored | 0 | 0 | 0 |
| Pending or failed extraction jobs | 0 | 0 | 0 |
| Future episode explicitly labeled as plan in context | no | yes | yes |

The initial baseline console counted only facts for extraction/validation (11).
The baseline artifact corrects these counters to 13 using its two unchanged,
valid raw episode outputs. This is an accounting correction, not another test run.

Evidence (raw fictional responses, metrics and per-question contexts):
[baseline](memory-reliability-20261105/baseline.json),
[round 2](memory-reliability-20261105/iteration-2.json),
[final](memory-reliability-20261105/final.json).

## Proven causes

- **Extraction:** baseline omitted both explicit attributes of a named colleague
  and the relationship wish. Round 2 emitted a paraphrased wish rather than a
  literal substring; validation correctly rejected it. Explicit compact-profile
  person/wish schema examples improve these cases in round 3.
- **Retrieval:** `gesundheitlicher Status` matched stored source wording but the
  privacy gate recognized only the noun `Gesundheit`, dropping the correct fact.
  German health variants now authorize the relevant private recall; unrelated
  project questions still cannot retrieve the health claim.
- **Claim identity:** `_propose` has one current value per `(subject, field)`.
  A broad `status` can therefore block independent domains. Real SQLite guards
  now prove career/health coexistence, same-domain conflict preservation, temporal
  separation and resistance to invented model field suffixes. This structural
  issue did not produce a false conflict in this particular live baseline, whose
  extractor chose `beruf` and `gesundheit` instead of `status`.
- **Answer grounding:** episode retrieval previously labeled a future move as a
  reported experience. It now labels plans explicitly and includes literal periods.

## Implementation and backward compatibility

New validated status claims use readable domain keys (`status.beruflich`,
`status.gesundheitlich`, `status.beziehung`) inferred from source wording.
Ambiguous domains retain ordinary conflict review. Status values are never hashed;
model-created status suffixes are normalized before determining domain identity.
Same-domain alternatives still conflict. Existing set-valued fact behavior stays
in place. Plans use a separate `.plan` claim slot. Clearly past assertions use
`.vergangen` plus literal years when present. `seit` dates keep the current slot,
so changing a date cannot silently bypass a current-state conflict.

All original evidence remains attached through existing fact/conflict/episode
source tables. No migration, automatic resolution, deletion or reclassification
of old facts is performed. Existing broad legacy claims may coexist with newly
scoped facts and still require manual review. Named-person recall now recognizes
an explicitly requested stored person slug without requiring a redundant name fact.

## Validation and remaining failures

Round 2: 99 regression checks passed; one existing prompt-profile expectation
failed because both profiles now include shared claim rules. Round 3: **102 passed**
across claim identity, semantic memory, persistent knowledge and dedicated-model
checks. No browser suite or full regression suite was run.

**Before the partner-only follow-up, the acceptance command exited 1.** Round 3 regressed partner
identity: it emits `personen.elara.beruf=Lehrerin`, omits a separate name fact,
and does not retain the required `partner` identity. The strict counter therefore
credits neither partner target, even though the source quote contains both words.
This is an extraction/identity failure, not missing SQLite storage or validation.
Do not treat the 102 passing checks as complete memory acceptance.

The compact-model prompt remains sensitive to changes, even at temperature 0.
No universal recall or hallucination guarantee follows from this small corpus.
Zero unsupported values means literal source support on this corpus, not proof
of correct semantics for arbitrary model output. Temporal scoping is conservative:
undated past assertions remain in one past slot, overlapping intervals and named
entities/relationships are not resolved by a general timeline/entity system.
Existing 45 production conflicts remain untouched and were not privately inspected.

The original three-round limit was honored. The separately authorized partner-only
follow-up above resolves that recorded regression in replay. This draft is not a
production deployment request; current live-model confirmation remains unavailable.

## Local reproduction

From this checkout, use the captured real-model responses to reproduce the final
16/16 result with fresh temporary SQLite storage, without any running service:

```sh
python3 scripts/accept-memory-reliability.py --replay docs/validation/memory-reliability-20261105/final.json --report /tmp/nobby-memory-review.json --check
```

Expected exit status: **0**, with 16/16 source-backed retrieved targets.
For another real-model evaluation, replace `--replay ...` with `--live --model
/absolute/path/to/already-running-4B-model`; do not launch a model for this script.
