# Persistent Intelligence Memory 3: integrated retrieval and evidence

Development date: **2026-11-06** (Europe/Berlin). This extends the existing
SQLite/Qwen memory pipeline. It does not introduce a second memory service,
download a model, migrate production data, restart services or scan private
history. See [reproducible measurements and release gates](validation/memory3-20261106.md).

## Repository and GitHub inventory

Development started from `main` at `cd5f977a438083033de6fefb0fcef3b18b920479`
on `feat/persistent-memory-3-20261106`. GitHub was checked before edits:

| PR | Actual state on 2026-11-06 | Treatment |
| --- | --- | --- |
| [421](https://github.com/nfekete82/mlx-nobby/pull/421) | Open draft, head `57126935` | Existing integrated source/version/episode architecture retained |
| [424](https://github.com/nfekete82/mlx-nobby/pull/424) | Closed, **not merged**, head `3efe71dc` | Historical reports examined; no merge inferred from closure |
| [438](https://github.com/nfekete82/mlx-nobby/pull/438) | Merged, head `3549779c` | Owned 4B/media handoff and foreground priority preserved |
| [440](https://github.com/nfekete82/mlx-nobby/pull/440) | Merged, head `e29c2f0c` | Independent explicit-store fallback retained and extended to normal recall |
| [441](https://github.com/nfekete82/mlx-nobby/pull/441) | Open, head `b8306901` | Reviewed actual diff; its game-compound scenario is covered by generalized vocabulary/component matching; no merge or closure performed |

The code and tests in the actual base, rather than PR descriptions alone,
determine what is already available. Prior real-model test reports are
historical evidence; they are not new Memory 3 model validation.

## Existing architecture and integration points

| Component | Current responsibility |
| --- | --- |
| Authoritative chat JSON and retained source vault | Original turns/revisions; visible chat deletion follows existing explicit retention policy |
| `chat_archive.py`, `chat-archive.sqlite3` | Incremental FTS5 transcript/activity/revision index and original source excerpts |
| `personal_memory.py`, `personal-memory.sqlite3` | Current and historical facts, lineage, conflicts, source exclusions and forgotten attribute rules |
| `knowledge_memory.py`, same personal database | Source revisions/evidence, episodes, entities/relations, typed claims, tombstones, durable segmented jobs, FTS and vectors |
| `semantic_personal_memory.py` | Existing single background worker, bounded wake-up queue, source revalidation and grounded 4B output validation |
| `smart_full_history.py` | Explicitly authorized resumable discovery; durable jobs survive full queues and interruptions |
| `dedicated_memory_model.py`, supervisor/coordination | Selected local Qwen endpoint, inference lease, foreground/media priority and ownership protections |
| `memory.py`, `memory.db` | Compatible older notes/preferences and existing hybrid recall |
| `memory_embeddings.py` | Loopback-only embedding transport, vector validation and bounded background batches |
| `memory_lifecycle.py`, middleware | Per-turn recall, bounded workers/deadlines, context assembly and fallback |
| Memory overview/inspector | Existing inspection, corrections, history, relationships, job errors, pause, storage scopes and new retrieval diagnosis |

No persistent schema change is needed here. Extractor version 5 and existing
durable jobs are preserved. Existing processed sources are not silently
reanalyzed, nor are previously stored assertions automatically erased by the
new conservative source filters. Review/reprocessing remains an explicit
local action governed by existing retention controls.

## Reproduced failures and implementation

**Lexical mismatch and corpus-dependent ranking.** Unicode normalization,
inspectable German/English/Hungarian concept families and conservative
inflection roots feed the same FTS5 index. A connection-local `fts5vocab`
view supplies actual indexed compound terms; the algorithm handles previously
unlisted compounds such as music-collection and ship-position systems.
The existing game case is also covered when the stored text contains only
`Browserspiel`, with no second `Echtzeitstrategiespiel` token. `Beispiel` is a
stopword, avoiding an accidental game-topic expansion.

Queries have at most 96 rewritten terms; vocabulary expansion examines at
most 20,000 indexed tokens; lexical candidates are capped at 256. BM25 is
normalized before combination with overlap, recency, pins and local cosine
scores, so its changing scale cannot dominate the other signals as data grows.
These are deliberate work bounds, not an exhaustive large-vocabulary index.

**Cross-chat project linking.** Explicitly named first-person project reports
can be learned deterministically without a remember command or available 4B.
Literal descriptions enter the existing `projekte.<name>` subject namespace,
fact evidence and relation tables. Named project retrieval expands to its
active attributes from other source chats and excludes other typed projects.
It does not invent technologies, infer completion or create causal edges.
Identical values on different subjects are not collapsed during selection.
Names require complete stored name tokens to establish an entity anchor;
ambiguous aliases are not automatically merged.

**Literal quotes are not personal assertions.** Deterministic extraction and
semantic fact/episode validation share conservative source checks. Quoted
assertions, code blocks, Markdown quotations, attributed model text,
hypotheticals and questions cannot become biographical facts merely because a
value occurs literally. A real assertion after a quoted example can still be
learned. Credentials continue to be rejected before processing. These filters
are conservative heuristics: quoted labels and complex indirect speech may
need review; this is not a complete linguistic attribution parser.

**Explicit semantic recall.** The explicit middleware path can now search
already indexed local vectors. An empty vector index makes no service call.
A cold health probe is limited to 50 ms and the query request to 150 ms;
network errors fall back to lexical evidence, including when error diagnostics
fail. The embedding proxy advertises resident-query support and its loaded
state; foreground requests set `require_loaded: true`. Missing support, an
unloaded model or a model unloaded after the health probe takes the lexical
fallback. The proxy rejects a cold request before its load/admission path.
No foreground backfill or intentional cold model start is added. Query vectors are cached
for 30 seconds in a 64-entry process-local cache keyed by database, model,
dimensions and query digest; evidence selections are always reread. Deleted,
inactive, stale-digest, wrong-dimension and malformed vectors cannot provide
semantic evidence. Socket timeouts are not a hard total scan-time guarantee;
the existing outer chat deadlines and bounded executor remain necessary.

**Fault isolation, contradictions and context.** Normal recall now reads
clarification/personal/knowledge sources independently, like explicit recall.
One source or diagnostic failure cannot discard the other results. At an
explicit semantic deadline, recall retries the independent SQLite-only path, so a
slow vector scan cannot erase otherwise available personal evidence. Current
facts with unresolved proposals carry a contradiction warning on their own
line, so dropping a separate proposal to fit the budget does not establish the
old value as confirmed. Low-confidence reports are labeled. Context assembly
shares the budget across sources and retains complete source lines. The
existing intent tiers remain: normal added personal/knowledge context up to
9,000 characters and fast explicit assembly up to 26,000. These are character
budgets, not adaptive tokenizer-exact windows or a claim that all history fits.

## Dashboard and diagnosis

The existing knowledge cards now show saved/updated timestamps. Existing
sources, correction history, typed plans/assumptions, relationships and job
progress/errors remain available. No new deletion or retention rule is added.

**Settings → Memory → Context Inspector → Diagnose all memory stores** uses:

```text
POST /api/mlx/memory/knowledge/diagnose
Native Agent: POST /api/knowledge-memory/diagnose
Body: {"query":"Wie heißt mein Strategiespiel?"}
```

The response shows the resolved recall query, rewritten/index terms,
independently searched stores, candidate count, selected structured sources,
ranking components, status, omitted count, source IDs actually present in the
assembled context, elapsed time and the complete fast-context preview.
Pause, unavailable sources and no matching evidence have separate explanations.
This is a reproduction of the **fast fallback path**, not a log of a previous
chat, a rerun of its embedding branch, or proof of what an answer model used.

New diagnostics use a POST body and `Cache-Control: no-store` at both API
layers. They do not persist queries, source values, retrieval selections or
usage counters, or send them to GitHub. Exception classes are used for errors.
The existing legacy-only GET inspector remains compatible; its query parameter
can appear in HTTP access logs. Diagnostic results are private local content;
do not attach them to public issues. Browser rendering uses text nodes and
encoded local source links, including for stored hostile HTML.

## Retention, recovery and historical processing

The existing explicit Settings deletion scopes, private source vault,
tombstones, source exclusions and import/replay guards remain authoritative.
Deleting visible chat history does not automatically remove retained memory.
Chat text is not permission to delete knowledge. Pause preserves knowledge
and suppresses automatic retrieval/learning. Old exports cannot override newer
local deletion rules. Query caching cannot recreate deleted knowledge.

Existing full-history discovery is durable and opt-in. Its status reports
queued/completed/excluded/error/stale segments and discovery completion; a
scheduled scan alone does not establish that all sources were successfully
processed. Tests already cover long messages, revision changes, queue overflow,
interruption, source read failures, pause and bounded retries. This development
did **not** enumerate or index production private chats. It therefore cannot
certify the completeness of a particular private installation.

Before a separately approved production migration or backfill, create and
verify a private backup outside the repository. The existing backup utility
uses SQLite's online backup API, integrity/schema/count checks and file hashes.
Restore/export tests use only fictional databases. No new migration is required
for this change; retaining that backup gate protects older installations too.

## Safe Mac checkout and acceptance

These commands prepare an isolated review installation and CPU/browser checks.
They do not switch production models or restart any service:

```bash
cd ~/mlx-web
git fetch origin feat/persistent-memory-3-20261106
git worktree add ../mlx-nobby-memory3-review origin/feat/persistent-memory-3-20261106
cd ../mlx-nobby-memory3-review
python3.13 -m venv /private/tmp/mlx-memory3-tests
/private/tmp/mlx-memory3-tests/bin/python -m pip install -r requirements/test.txt
/private/tmp/mlx-memory3-tests/bin/python -m pip check
/private/tmp/mlx-memory3-tests/bin/python tests/acceptance/official_pytest.py |
  xargs -0 /private/tmp/mlx-memory3-tests/bin/python -m pytest -q
node --test tests/*.mjs
/private/tmp/mlx-memory3-tests/bin/python scripts/i18n-audit.py
/private/tmp/mlx-memory3-tests/bin/python scripts/check-public-privacy.py
/private/tmp/mlx-memory3-tests/bin/python -m playwright install chromium
/private/tmp/mlx-memory3-tests/bin/python -m pytest --e2e -q tests/e2e
/private/tmp/mlx-memory3-tests/bin/python scripts/benchmark-memory3.py \
  --report /private/tmp/memory3-acceptance.json
```

Optional private backup before a later authorized rollout (never upload):

```bash
memory3_backup="$HOME/Backups/mlx-memory3-$(date +%Y%m%d-%H%M%S)"
/private/tmp/mlx-memory3-tests/bin/python scripts/backup-local-state.py \
  --destination "$memory3_backup"
/private/tmp/mlx-memory3-tests/bin/python scripts/backup-local-state.py \
  --verify --destination "$memory3_backup"
```

Production adoption requires the reviewed revision in the actual service
checkout plus the normal controlled Agent/web/embedding-proxy update procedure. A review
worktree alone does not update launchd's source path or the Docker web image.
Until the embedding proxy is updated, foreground recall safely stays lexical.
The 4B/27B model settings and supervisor/media rules need no change. Do not use
the historical `local-update.sh` as a Memory 3 installer: it targets a different
fixed integration branch. Do not launch another GPU server for these CPU checks.

Separately approve any private historical scan, running-4B/27B answer test and
48 GB media-concurrency/swap acceptance. Synthetic retrieval does not establish
those results or unrestricted semantic recall quality.
