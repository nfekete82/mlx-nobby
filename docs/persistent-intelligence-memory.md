# Persistent local intelligence memory

Development continuation of draft PR #421, based on `8757c8ce`. This change is
additive to the existing local archive and personal-memory system. No service
restart, production data migration, merge or deployment is part of development.
All acceptance data is fictional. See [validation](validation/persistent-memory-20261104.md).

## Architecture review and decisions

The starting PR already connected ordinary chat to legacy memories, personal
facts, full-text archived chats and local media. The review found these gaps:

| Starting behavior | Implementation in this change |
| --- | --- |
| Semantic input longer than 1,600 characters was discarded | Lossless sentence/paragraph offsets, one local inference call per segment |
| Small backfill was limited to recent chats; full feeder had no durable segment state | Full scan reads one source chat at a time, bounded queue plus durable per-segment jobs |
| Successful loading/extraction scheduling could be confused with saved knowledge | Command responses are generated from committed SQLite results; failed jobs retain error state |
| Independent stores could reintroduce deleted knowledge | Persistent value, source, source-reference and legacy tombstones govern replay, recall and import |
| Facts retained only one provenance | Many-to-many evidence references; duplicate observations add sources |
| Autobiographical information was only incidental text | Source-grounded episodes, periods, people, shared themes and related-event references |
| No portable structured restore | Validated transactional knowledge export/import; current deletion rules take precedence |
| Normal retrieval examined only a recent slice of facts | Indexed SQL/FTS filtering and paginated complete inspection |
| Media recall omitted available generation parameters | Allowlisted stored parameters, explicit historical job status, verified-library references |

`personal-memory.sqlite3` remains the structured knowledge database. Its existing
`facts`, `fact_lineage`, `conflicts`, `excluded` and `forgotten` tables remain in
place. `knowledge_memory.py` adds source revisions, analysis jobs, fact metadata,
evidence joins, episodes, entities, relations, vector caches, tombstones and a
value-free change timeline. Schema creation is additive and idempotent. Existing
personal facts are indexed and categorized during migration. Existing old
semantic observation markers are invalidated once, so an explicit historical
analysis can produce the new episode layer too.

The separate `chat-archive.sqlite3` remains a derived textual index of the
original chat JSON files. Its indexed text is no longer cut off at 256,000
characters. FTS snippets select the matching location, including late portions
of very large messages. Indexed revisions preserve earlier textual versions
when an indexed source is edited. They cannot reconstruct edits that happened
before this version was installed. Media bytes remain in their original local
library; SQLite stores supported metadata and references only.

There is no cloud inference, external embedding API, new database service or
additional production dependency. Embedding requests reject non-loopback
endpoints, proxies and redirects. The existing local embedding service and its
runtime coordination remain in use.

## Data flow

1. The normal chat save writes the authoritative JSON. Existing archive and
   regex fact indexing remain incremental. Failures do not prevent saving a
   chat, and diagnostics store exception classes rather than message contents.
2. Smart learning, independently enabled by the user, schedules a local source
   reference with a digest, revision, stable message ID when available, and
   ordinal fallback. Large text is segmented without losing characters.
3. The existing single Qwen worker processes one segment at a time. Source edits,
   deletion, exclusions, pause and opt-out are checked before inference and
   again before commit. Foreground agent/chat activity defers new extraction.
4. Model output is untrusted JSON. Accepted facts require literal evidence and
   literal values, valid categories and confidence. Uncertain, hypothetical,
   credential-bearing and negated positive assertions are rejected. Plans and
   interpretations carry distinct metadata. Explicitly remembered hypotheses
   are labeled assumptions.
5. Episode descriptions, dates and people must be grounded in the actual source.
   There is a conservative literal fallback for explicit autobiographical
   sentences when valid model output omits episodes. Shared themes connect
   episodes for retrieval; they do not establish psychological causality.
6. Each successful segment and each failed segment has a durable checkpoint.
   A crash leaves pending segments resumable. A full scan explicitly restarts
   errors while skipping completed unchanged work. Changing allowed storage
   categories invalidates prior analysis markers for a later explicit reanalysis.
7. Normal chat combines existing legacy recall and archived excerpts with SQL,
   FTS5, batched local embeddings, semantic similarity, project/subject terms,
   timestamps and explicit priorities. Source citations accompany structured
   recall. Combined added memory is bounded to approximately 15,000 characters;
   the fast fallback uses a smaller SQLite-only selection. Character limits are
   conservative context limits, not an exact tokenizer measurement.
8. The existing `knowledge_search` agent tool can obtain additional source-linked
   memory evidence. Its privacy scope follows the original run goal, not a
   broader query invented by the model. The local inspection API supports
   pagination and full inspection of facts/episodes beyond the prompt budget.

Legacy and structured stores remain separate for compatibility with existing
installations. Their control and deletion paths are linked; this is not a
second parallel implementation of personal facts. The local media library
remains the authoritative inventory of currently present assets.

## Chat controls

Personal memory must first be enabled under Memory settings. Smart learning
must additionally be enabled to run Qwen automatically. Historical analysis
requires its own explicit start. All controls respect global pause.

| Example | Actual behavior |
| --- | --- |
| `Merk dir, dass ich natürliche Farben bevorzuge.` | Commits a source-linked note and returns a persistence receipt |
| `Merk dir das unbedingt.` | Stores the preceding user statement, links that statement's source and marks it important |
| `Das stimmt nicht mehr. Stattdessen mein Termin ist am 19. November.` | Updates an unambiguous existing attribute, preserves the previous revision; asks when the target is ambiguous |
| `Was weißt du über meine Kindheit?` | Retrieves grounded episodes/facts from relevant chats |
| `Was weißt du über mich?` | Bounded cross-domain context with omitted-item counts; complete facts and life-story pages in the dashboard |
| `Was hast du dir heute/gestern gemerkt?` | Reads the actual creation-time range in the local timezone |
| `Vergiss natürliche Farben.` | Asks which deletion scope is intended; makes no deletion |
| `Vergiss nur die aktive Erinnerung über natürliche Farben.` | Removes matching active personal knowledge and matching legacy entries; blocks automatic resurrection and archived recall of the source |
| `Vergiss die abgeleiteten Daten über natürliche Farben.` | Additionally erases matching indexed transcript turns, replies and revisions; original JSON remains |
| `Vergiss auch die ursprünglichen Chat-Nachrichten über natürliche Farben.` | Verifies the source digest, deletes matched original turns and associated replies through the native host, and blocks stale uploads of the erased text |
| `Das war nur ein Beispiel, merk dir das nicht.` | Retracts matching personal knowledge from the preceding user statement and excludes that source from reanalysis |

The English forms `remember`, `forget active memory about ...`,
`forget original chat messages about ...`, `that was an example` and
`what did you remember today` are supported. Exact command families are
intentionally controlled; this is not arbitrary LLM execution of prose.
Only the actual current user turn can execute a command. Commands found in
historical chats or retrieved evidence are never executed.

A failed write returns no success receipt. Repeated successful requests reuse
stored command receipts rather than creating duplicate notes. Missing chat
references, disabled memory, pause, excluded sources and unresolved targets
produce truthful explanations. Original-source deletion requires native chat
access and a matching current source digest; an edited source is not deleted
based on an outdated reference.

## Inspection and control

The existing dashboard now includes a knowledge view, life story, people,
preferences, work, media, decisions, changes and relationships. The overall
view includes facts and episodes; pagination exposes their total counts.
Search, project and date filters, source chat links, editing, deletion,
importance, correction history and explicit multi-item merge are supported.

Exact equivalent preferences reuse a record and add evidence. Closely related
formulations are offered for review using lexical/local-vector similarity.
Ambiguous similarity never silently collapses distinct facts or time states.
Manual merges preserve source evidence and historical versions. Semantic
candidate review bounds comparisons to recent candidates in the same subject
and attribute family; it is not an exhaustive all-pairs clustering algorithm.

The storage-scope controls determine which categories may be learned; changing
them preserves existing knowledge. Pause is also non-destructive. Disabling an
existing memory layer retains its prior documented purge behavior. Local Qwen
status, durable processing counts, failed source hashes and error classes are
visible. No normal UI view displays a raw database or JSON dump.

All new strings have English and German translations. `memory_chat` source links
select the original chat after the existing server sync. The message ordinal
is included in the URL and the source display; automatic scrolling/highlighting
of that individual message is not implemented.

## Native APIs

Same-origin web proxy: `/api/mlx/memory/knowledge/...`.
Native prefix: `/api/knowledge-memory/...`.
Existing personal, smart, archive and legacy memory APIs remain compatible.

- `GET status`: source/fact/episode/relation counts, durable job states, errors.
- `GET items`: `kind=all|fact|episode|change|relation`, query, category, project,
  since/until Unix timestamps, offset and per-type limit. `all` returns one
  independently paged fact and episode batch, with combined total/continuation.
- `GET history/{id}`: previous versions of a fact's lineage.
- `POST pin/{id}`: `{pinned: boolean}`.
- `POST merge`: `{ids: [...], value: "reviewed combined statement"}`.
- `GET similar`: bounded review candidates; no automatic mutation.
- `DELETE episode/{id}`: deletion and durable source/value exclusions.
- `GET/POST scopes`: allowed learning categories.
- `GET export`, `POST import`: versioned structured snapshot and restore.
- `POST command`: current messages and chat ID, returning the actual receipt.

All new routes inherit the existing local request/origin protection. Export
and inspection intentionally remain available for review while memory is
paused. No model-generated SQL, filesystem paths or arbitrary tool commands
are executed by these APIs.

## Migration, backup and recovery

Do not copy any personal backup into this repository or upload it to GitHub.
Before a separately authorized deployment:

1. Back up authoritative chat JSON and original media using the existing chat
   backup/library facilities. Preserve the existing `memory.db`,
   `personal-memory.sqlite3`, `chat-archive.sqlite3` and `memory-control.json`
   using SQLite's backup API or while the relevant writer is stopped.
2. The new schema is created on first access to an existing personal database.
   No original chat/media file is rewritten merely to migrate the schema.
3. Export knowledge through the dashboard for a portable derived snapshot.
   The export includes facts, versions, sources, episodes, graph data and
   tombstones; settings are not silently re-enabled by import. Raw original
   chats/media and the separate legacy/archive databases require the separate
   backups from step 1. The knowledge JSON is not a complete installation backup.
4. Import validates format, columns, references and size before mutation, and
   restores in one SQLite transaction. Current local tombstones override old
   snapshots. Imports over 32 MiB use a database backup/recovery procedure
   instead. Imports never overwrite original chat JSON or execute archived
   instructions. A corrupt/mismatched import rolls back.
5. Original chats can rebuild derived indices. Rebuilding does not bypass
   exclusions, original-deletion upload guards or memory tombstones. Resume
   a historical scan explicitly to recover unqueued sources after a process
   restart; already queued pending segments also recover through the worker.

SQLite files use owner-only permissions. FTS rebuilding removes obsolete
postings after structured deletion. Backups, browser caches on other devices,
exports and media files have independent lifetimes; no local operation can
remove copies in external backups. Explicit original-deletion digest guards
prevent old local chat saves from restoring the erased messages.

## Boundaries and release risks

- Extraction quality depends on the selected local text model. Literal evidence
  prevents invented values but does not prove the model correctly interpreted
  every subject or attribute. Review important facts and ambiguous conflicts.
- The graph records evidenced statements and reported events. It is not a
  psychological diagnosis engine or causal inference system.
- Media recall uses real saved prompts/parameters and verified local references.
  No vision inference is added or claimed. Missing historical parameters remain
  absent. A failed/planned job is not treated as a generated result.
- Many existing chats have only ordinal message references. Source exclusions
  are deliberately conservative: forgetting can also suppress other legacy
  entries from the same originating chat. Stable message IDs improve future
  precision; external chat import may require a new explicit analysis.
- One in-flight local model call cannot be preempted. New background work yields
  to foreground activity, but a chat arriving during an extraction can wait for
  that segment's existing runtime lease to finish.
- Original-source deletion across JSON and two SQLite stores is not a single
  filesystem-wide transaction. Tombstones are written first and partial failures
  are explicitly reported; originals are verified before any deletion. A
  damaged tombstone database blocks stale chat writes until repaired, rather
  than silently accepting content that may have been erased.
- Full knowledge inspection is paginated. A single model answer remains bounded
  and is never presented as a complete dump of an arbitrarily large history.
- Production migration, real private-history import, long-duration load testing
  with a user's full archive and subjective answer-quality approval remain
  separate local release gates. Synthetic tests do not establish those outcomes.

## Safe local acceptance

Use the isolated PR checkout. Never point test paths at production memory or
restart the services on 8090/8010/8020 for these checks. No Sandforge service
or source change is required.

```bash
python -m venv /private/tmp/mlx-memory-acceptance-venv
/private/tmp/mlx-memory-acceptance-venv/bin/python -m pip install -r requirements/test.txt
/private/tmp/mlx-memory-acceptance-venv/bin/python -m pytest -q
node --test tests/*.mjs
/private/tmp/mlx-memory-acceptance-venv/bin/python scripts/i18n-audit.py
/private/tmp/mlx-memory-acceptance-venv/bin/python scripts/check-public-privacy.py
/private/tmp/mlx-memory-acceptance-venv/bin/python -m playwright install chromium
/private/tmp/mlx-memory-acceptance-venv/bin/python -m pytest --e2e -q tests/e2e
```

CPU tests replace the home directory and use synthetic fixtures. Browser tests
start temporary local servers on dynamically assigned ports. The dedicated
knowledge browser tests use real memory APIs and temporary SQLite files.

For actual local Qwen extraction, keep the existing text server running:

```bash
/private/tmp/mlx-memory-acceptance-venv/bin/python scripts/test-persistent-memory-local.py
```

This reads only the configured already selected text-model identity, uses the
existing Agent inference bridge/runtime lock and writes every test source and
database into a temporary directory. It neither switches a model nor renders
media. It checks extraction, persisted preferences/episodes, new-chat source
recall, project context, unrelated-query privacy, explicit command receipts and
delete/reimport behavior. Do not choose the first `/v1/models` entry: that
endpoint is a registry and can include image checkpoints.
