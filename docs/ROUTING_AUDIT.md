# Routing audit (2026-10-01)

Baseline: main / origin/main `7f2dc86` (fetched before changes).

## Findings before changes

The browser (`frontend/assets/chat/generation.js`) computes independent image,
edit and video regex hints, calls web preflight, and falls back to those hints
when preflight fails. Options can also supply a media fallback. Multiple-image
turns sometimes bypass preflight. A single attachment normally enters it.

`backend/app.py` proxies both action endpoints to the Agent. Production
`backend/entrypoint.py` installs a response middleware plus monkey-patched
prompt and portrait guards. These only modify preflight responses. High router
confidence can authorize image/video without explicit execution. Observatory
storage includes raw prompt previews, which may contain personal data.

`agent/app.py` has deterministic, semantic and manager classifiers and another
execution-time priority chain. Shorts and video matching precede vision;
validated client targets precede all language checks. Image-edit matching uses
verbs anywhere in the sentence, including prompt improvement. Portrait intent
is extended separately by `agent/image_generation_intent_runtime.py`.

Root cause: the requested output (text versus media) is not a shared invariant.
Creation verbs can bind to a later media noun across the actual object `prompt`.
A preflight demotion does not prevent execution-time classification or a stale
client target from starting media. Adult vocabulary and attachments must never
supply execution intent.

`agent/runtime_tools.py` starts image/video/Shorts jobs directly, outside the
chat-action router, using tool queries that can differ from the user goal.
Dedicated media UI endpoints are explicit execution surfaces and retain their
existing permission, source ownership and revision checks.

`agent/vision_routing.py` already prefers `vision_uncensored` whenever available,
regardless of the safety classifier. Classification remains metadata. No change
is needed to that policy.

## Implemented order

1. Shared `backend/media_intent.py` reads the current instruction. A small lexical
   command/object parser treats text-output objects (prompt/script/description),
   questions, quoted examples and withheld execution as chat. Model names,
   adult words and attachment presence never supply an execution command.
2. Explicit command + media output authorizes generation, edit, animation or
   Shorts; existing image modifiers support contextual edit follow-ups.
   Independent explicit execution clauses remain supported ("improve the prompt
   and generate the image").
3. Explicit media UI actions support bare descriptions, but cannot override text
   output or withheld execution. `resolved_target` is only a hint. A chat target
   suppresses media execution after failed preflight.
4. Images without execution stay in chat/VLM. Non-media requests retain the
   existing workspace, web, semantic router, manager and agent permission gates.
   Semantic media predictions cannot authorize execution.
5. The action endpoint uses the same decision and dispatches existing pipelines.
   Runtime media tools validate the original bound user goal, including across
   delegated/rephrased tool goals. Job status queries remain read-only.
6. Web response middleware uses the same decision. The compatibility meta and
   portrait modules no longer install independent regex policies. Browser hints
   bind resources only; single- and multiple-image turns both use preflight;
   failed preflight returns to chat. An active reference
   image can be loaded for vision after a chat decision despite local edit hints.

`RoutingDecision` exposes intent, target, execution_requested, media_context,
confidence, reason, guard and fallback. Confidence is certainty of the rule,
not an LLM probability or permission substitute. Web telemetry retains the
original and final targets, hash, length and timing; prompt previews are redacted,
including historical records when read. Attachment payloads are not persisted.
Dedicated media UI endpoints remain explicit execution surfaces.

## Regression coverage and remaining boundaries

`tests/test_media_intent.py` runs the German/English matrix through actual
preflight/action HTTP endpoints and the web middleware, with job dispatch mocked.
It checks stale targets, explicit actions on prompt requests, adult vocabulary,
active artifacts, negation, quoted examples, image modifiers, mixed execution
clauses, privacy, and rewritten/delegated runtime goals. Browser integration
checks image-context text requests and failed preflight without a media modal.
Existing tests expecting generation from bare descriptions or high classifier
confidence now require explicit execution instead.

This is a conservative German/English command parser, not a general language
parser. Unsupported languages, indirect execution wishes and novel ellipses
fall back to chat. Unquoted multi-clause prose containing imperative media
commands can still be interpreted as execution; quote pasted prompt examples.
Execution negation spanning independent clauses remains conservative and can
suppress a legitimate mixed request. The final independent media command wins when several are requested;
there is no newly implemented multi-job orchestration. Existing media source
ownership, revision checks, queue behavior and permissions remain authoritative.
Tests mock models and job launch; they do not render real media or assess VLM
answer quality.

## Scoped negation

Negation before the command, a negative output determiner (`kein Bild`), or a
negated command without an appearance property still withholds execution.
Negation after the command that qualifies a requested appearance (`nicht so dunkel`, `not so bright`) does not cancel the edit. Image referents such as
`hair` and `background` are excluded from the appearance-property vocabulary,
so `edit not the background` still withholds execution. This scope analysis
lives exclusively in the shared policy and applies to preflight, dispatch,
web guards and runtime tools. German/English endpoint regressions cover both
scopes and stale media hints.

## Validation

- Full Python suite: 1,167 passed plus 296 subtests, with two existing dependency
  deprecation warnings. Run with `PATH="$PWD/agent-venv/bin:$PATH"` so subprocess
  Python syntax checks use the project interpreter.
- JavaScript suite: 115 passed, including browser regression cases.
- Python/JavaScript syntax, tracked JSON, i18n audit, shell syntax and launchd
  plist validation passed.
- Docker Compose configuration and the web-image build passed.
- `git diff --check` passed; sync marker was not changed.

The existing video RAM-handoff test also failed on unchanged main because its
fixture did not simulate pressure at `runtime_coordinator.memory_budget_snapshot`.
The fixture now provides critical pressure explicitly; production video runtime
behavior was not changed. Docker validation builds an image; it does not restart
or deploy running services.
