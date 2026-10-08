# Local OpenAI-compatible inference API

Base URL: `http://127.0.0.1:8090/v1`.

This is stateless inference for external agents such as Cline. Cline supplies
the conversation, receives function calls and executes its own tools. Nobby
does not run AgentRuntime, enrich prompts with memory/RAG, select workspaces,
inherit image context, or save these requests as sidebar chats.

The web service relays fixed endpoints to the native host. The host takes the
existing Runtime Coordinator chat lease before the shared model lock, resolves
the configured role deterministically, and calls native MLX Chat Completions.
Existing media handoff and model-switch rules remain in effect.

## Endpoints and models

- `GET /v1/models`: OpenAI model list, containing configured available roles.
- `POST /v1/chat/completions`: JSON completions or native SSE.

Virtual model IDs are `mlx-nobby/coding`, `mlx-nobby/chat`, and `mlx-nobby/agent`.
The last one selects the model assigned to that role; it does not execute the
Nobby agent. Role changes take effect on the next request. Unavailable roles
are omitted from the list and produce a controlled 503 on inference.
Direct aliases and filesystem model IDs are intentionally not accepted: the
external API exposes only role IDs, without disclosing model installation paths.

Supported parameters: `model`, `messages`, `stream`, `temperature`, `max_tokens`
or `max_completion_tokens` (not both), `stop`, `top_p`, `seed`,
`presence_penalty`, `frequency_penalty`, `tools`, `tool_choice`, and
`stream_options.include_usage`. Unknown fields produce 400 rather than being
silently ignored. Only one completion and text messages/content parts are
supported. Message roles: system, user, assistant and tool.

Function definitions, assistant tool calls and matching `tool_call_id` results
pass through the native model template/parser. Streaming preserves indexed
function deltas. Actual function support depends on the configured model and
runtime; a gateway cannot add that capability to a text-only model.

Literal stop sequences are checked across content-chunk boundaries. The
gateway retains only possible partial stop prefixes, then closes upstream SSE
when a stop matches. It does not interpret natural language or tool markup.
Usage is omitted if that early stop prevents native finalized usage.

## Cline setup and contract

Select **OpenAI Compatible**, set the Base URL above, and choose
`mlx-nobby/coding`. Enable the model's tool capability. Disable image support
for this text-only gateway. Use an adequate local-model request timeout, e.g.
180 seconds initially, and adjust it using measured prefill time.

There is **no authentication; loopback only**. Omit the API key if your Cline
version allows it. If a client UI requires a nonempty field, use any explicit
placeholder. The gateway does not validate it, grant permissions with it,
forward it to MLX, or log it. It is not a security token.

Set context/output limits from your configured model's metadata and runtime
configuration; do not assume a universal context size. On the native host,
`curl http://127.0.0.1:8000/health` reports the effective context limit for the
currently loaded VLM model (use your configured runtime port). A model's
`config.json` may place `max_position_embeddings` inside `text_config`.
Context capacity is not a guarantee that your hardware can serve that many
tokens. Max output is a per-request budget, not the model's context capacity.

### Historical validation (v1.6.0)

These client/model measurements describe the release validation, not required
installed model settings or a fresh run of this documentation audit.

The installed Cline 4.1.22 provider source was checked against its
[official tagged implementation](https://github.com/cline/cline/blob/v4.1.22/sdk/packages/llms/src/providers/vendors/openai-compatible.ts)
and installed AI SDK transport: it appends `/chat/completions` to the base URL,
supports native function definitions/results, consumes indexed tool deltas,
sets `stream_options.include_usage`, and uses an abort signal. Its provider
factory permits missing API keys. This provider uses Chat Completions, not
Responses. `/models` supports client discovery; no model-detail, Assistants,
Files, Images, Audio or Responses endpoints are implemented.

**Validated with Cline 4.1.22 in VS Code:** an exact-marker text turn, native
`read_files` → tool result → final answer, `editor` followed by a verifying read
in a temporary workspace, multiple turns, and cancellation of an active task
by starting a new task. The runtime stopped the old generation after 562
tokens and answered the recovery task. The test used a separate VS Code
profile, without editing productive repository files. The installed coding
model's native parser was `qwen3_coder`; its effective context limit was
262144; the Cline test configured a 4096-token output budget, not a claimed
model maximum. These measurements describe that tested model, not every role/model.

One idle, warm-cache measurement gave 159 ms gateway TTFT. Time outside native
generation was 33 ms through the gateway versus 6 ms directly (about 27 ms
added); maximum content-chunk spacing was 37 ms versus 34 ms directly. This is
a single local sample, not a universal benchmark. Existing coordinator waits
for concurrent media work and native prefill can dominate end-to-end latency.

## Examples

```sh
curl http://127.0.0.1:8090/v1/models

curl http://127.0.0.1:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mlx-nobby/coding","messages":[{"role":"user","content":"Say hello"}],"max_tokens":64}'

curl -N http://127.0.0.1:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mlx-nobby/coding","messages":[{"role":"user","content":"Say hello"}],"stream":true,"stream_options":{"include_usage":true},"max_tokens":64}'
```

SSE ends with `data: [DONE]`. Non-stream requests are assembled from the
runtime's native SSE as well, allowing client disconnects to close upstream
generation instead of leaving a blocking native non-stream call running.
Only actual runtime usage is returned; absent usage is omitted. Internal
observability can additionally report explicitly labelled estimates.

## Security and troubleshooting

Keep the existing Docker port mapping at `127.0.0.1:8090` and native services
on loopback. No new listeners or CORS permissions are introduced. The existing
local Host/Origin/body-size guard applies. Other local processes can access
this unauthenticated API. Do not expose it to a LAN or the internet.

400 means malformed messages/options or unsupported parameters; 404 means an
unknown model ID; 415 means an incorrect content type; 503 means unavailable
configuration/runtime. Stream failures after headers use an OpenAI error
envelope inside SSE and terminate the stream. Diagnostics do not include
prompts, tool contents, API keys or native installation paths.

If the endpoints return 404 after updating, rebuild the web container and
restart the native agent so both load the new route layer. If generation waits,
check ongoing chat/media work and the Runtime Coordinator rather than launching
a competing runtime. Never download or switch models just to satisfy a guessed
Cline capability. Verify native tool calling for the selected model first.

## Finance Intelligence API boundary

Finance decision support is exposed through the existing Chat action path and
`POST /api/mlx/finance/{tool}` (Agent: `/api/finance/{tool}`). It shares the
AgentRuntime ToolRegistry and permissions. These are native application APIs,
not changes to the stateless `/v1/chat/completions` protocol. External clients
can call the native Finance API explicitly; no finance provider calls are
automatically injected into `/v1` requests. See [Finance](FINANCE.md).
