# Independent local Memory model (opt-in)

The chat model and the long-term-memory extraction model can now be separate.
**Default is unchanged:** extraction uses the existing \`chat\` role, including
the same durable SQLite jobs, evidence rules, exclusions, and restart recovery.

Dedicated mode sends ONLY extraction requests to a separately running,
OpenAI-compatible model at \`http://127.0.0.1:8011\` (configurable port).
It never selects, unloads, or swaps the chat model on port 8000.
Neither mode uploads private prompts to a cloud provider. The endpoint is
built from the loopback address and a validated local port; redirects and
environment HTTP proxies are disabled. There is no arbitrary model URL setting.

## Why a separate process?

The current main inference server only has one active model. Routing an
alternate role through that same server would swap the foreground chat model,
causing latency and making extraction dependent on chat model switches.

The separate process is **not launched automatically** and remains
**disabled by default**. It consumes additional unified memory while running.
Before enabling, allow the existing history backfill to finish and verify
sufficient RAM/headroom. Do not start the second model during image/video jobs
or when memory pressure is high.

The existing durable memory worker continues to yield to foreground chat
activity and can resume its SQLite checkpoints. If the dedicated endpoint
fails, extraction errors remain visible and retryable; it does not silently
fall back to a different model or lose original chats.

## Start a local small model (manual, for acceptance)

Use a local, cached model directory. The following is an example only:
it requires the listed model to exist on disk. It does not download anything.

\`\`\`bash
cd ~/mlx-web
MODEL="$HOME/Models/router/Qwen3.5-4B-MLX-4bit"
test -f "$MODEL/config.json" || { echo "Local model missing: $MODEL"; exit 1; }
test -z "$(lsof -tiTCP:8011 -sTCP:LISTEN)" || { echo "Port 8011 is in use"; exit 1; }
./runtime-venv/bin/python scripts/runtime-model-backend.py "$MODEL"
# If the preceding command returns 'vlm':
./runtime-venv/bin/python -m mlx_vlm server \
  --model "$MODEL" --host 127.0.0.1 --port 8011 \
  --prefill-step-size 512 --max-num-seqs 1
# If it returns 'lm', use mlx_lm.server with the same model/host/port instead.
\`\`\`

Use a second terminal to inspect exactly which model ID the server advertises:

\`\`\`bash
curl -fsS http://127.0.0.1:8011/v1/models | python3 -m json.tool
\`\`\`

After the existing production history processing has completed and you have
checked free memory, enable the independent memory role via local API (the
model must be online and the identifier must match \`/v1/models\`):

\`\`\`bash
python3 - <<'PY'
import json
import urllib.request

base = "http://127.0.0.1:8010"
with urllib.request.urlopen("http://127.0.0.1:8011/v1/models") as response:
    models = json.load(response)["data"]
model = models[0]["id"]
payload = json.dumps({
    "mode": "dedicated", "model": model, "port": 8011
}).encode()
request = urllib.request.Request(
    base + "/api/smart-memory/model",
    data=payload, headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request) as response:
    print(json.load(response))
PY
\`\`\`

Switching the normal chat model after this does not alter the stored memory
model configuration. Read it any time with:

\`\`\`bash
curl -fsS http://127.0.0.1:8010/api/smart-memory/model | python3 -m json.tool
\`\`\`

To restore the original single-model behavior:

\`\`\`bash
curl -fsS -X POST http://127.0.0.1:8010/api/smart-memory/model \
  -H 'Content-Type: application/json' -d '{"mode":"chat"}'
\`\`\`

Configuration is held inside the **existing private personal-memory SQLite
database** and is covered by the normal verified backup process. No second
memory store, memory migration, or re-analysis of finished messages is needed.

## Scope, privacy and adult-topic handling

- Every original chat remains in the private chat history/source vault
  according to the existing chat-retention and deletion/exclusion controls.
- Structured facts represent verified assertions, not every sentence.
- Explicit, user-stated adult intimate preferences are eligible for concise,
  sensitive, source-grounded facts; this is independent of whether the
  generation model is abliterated.
- Roleplay, hypothetical examples, generation instructions and passwords
  are not automatically asserted as biographical facts. Graphic descriptions
  need not be repeated as fact cards even though the underlying original chat
  can still be retained.
- A successful unit test of a normal model does not establish reliable extraction
  of NSFW content: real local model comparisons are required for that claim.

## Release and acceptance criteria

The small local model must be compared on the **same** private test fixture
as the current 27B chat extractor: fact precision/recall, duplicate count,
contradiction clarification, NSFW-specific adult factual inputs, refusal rate,
and latency. Keep personal source text and model outputs outside Git.
The application must preserve the existing 17+ facts, conflict history and
source vault when toggling roles.

The implementation has isolated HTTP/schema/regression tests. A complete real
4B-vs-27B quality benchmark and RAM-pressure acceptance require the user's
locally installed model weights and **cannot be validated by GitHub CI**.
Do not auto-enable, merge, or deploy before those gates pass.
