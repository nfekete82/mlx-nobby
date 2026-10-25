# Opt-in Vision Streaming (experimental)

The image-analysis chat bridge normally uses the non-streaming MLX-VLM response.
Native server support for `stream: true` depends on its installed version and
model. Do **not** enable streaming globally without testing the active VLM.

## Implementation and safety

- **Default OFF**: `MLX_CHAT_VISION_STREAM_ENABLED=0`. Only the Docker web
  container needs this environment variable. Text-only chat is unchanged.
- The web bridge still performs `/api/runtime/vision-route`, preserving image
  classification, model selection, and the chosen `vision` / `vision_uncensored`
  role. It then reuses the Agent's existing bounded, cancellation-aware chat
  streaming worker and its Runtime Coordinator lease.
- The Agent emits regular frontend `content`, `reasoning`, `metrics`, `done`
  and `error` SSE events. Vision requests with no text chunks return a
  protocol error, not a silent empty success.
- If the stream is unsupported, empty, or fails **before the first visible
  text chunk**, the web bridge retries using the original non-streaming
  completion route. Errors **after** a visible chunk do not replay the request:
  the user gets an error event instead of duplicated or contradictory text.
- The web relay never stores image data and does not enable any broader model
  routing or change memory-admission limits.
- `MLX_CHAT_VISION_FIRST_BYTE_TIMEOUT` (default 60 seconds, clamped to 30–300)
  bounds waiting on the web-to-Agent stream. Initial VLM prefill can be slow,
  so fallback can be slower than legacy on servers that do not support streams.

## Local smoke test

1. Confirm the selected vision model is already available, no video/image
   generation is active, and the production UI works in legacy mode.
2. With the repo updated, enable the experiment for the web container only:

   ```sh
   cd ~/mlx-web
   MLX_CHAT_VISION_STREAM_ENABLED=1 \
     MLX_NOBBY_BUILD_SHA="$(git rev-parse --short HEAD)" \
     docker compose up -d --build --no-deps mlx-web
   ```

3. Wait for `/chat` to return HTTP 200, then analyze a small non-sensitive
   image. Confirm incremental content and terminal `done`, without repeated
   text or unexpected error. Inspect the browser Network stream and Agent
   read-only observability; a functional UI alone does not prove token streaming.
4. To revert, redeploy the web container with the default feature setting:

   ```sh
   cd ~/mlx-web
   MLX_CHAT_VISION_STREAM_ENABLED=0 \
     MLX_NOBBY_BUILD_SHA="$(git rev-parse --short HEAD)" \
     docker compose up -d --build --no-deps mlx-web
   ```

The web probes `/api/runtime/vision-streaming/capabilities` before sending
its stream request. Older, still-running Agents lack this endpoint; they
automatically keep the legacy image-analysis path instead of selecting the
wrong model.

After merging/pulling this PR, restart **only the Agent** to load the updated
Python code, when no chat or media job is in progress:

```sh
cd ~/mlx-web
./scripts/mlx agent restart
```

Then verify its support via a read-only request:

```sh
curl -fsS http://127.0.0.1:8010/api/runtime/vision-streaming/capabilities
```

This should report `"supports_explicit_vision_role": true`. The MLX model
server and unrelated image/video/speech services do not need to restart.
Without Agent restart, the feature remains safe but cannot stream.

## Tests and measurements

```sh
./scripts/mlx test-quick tests/test_vision_streaming.py
```

The test fakes SSE chunks and checks that fallback happens only before the
first visible token. It does not prove the currently selected native VLM
supports streaming. A useful real benchmark records **first visible text**,
total completion time, and correctness for the same image and prompt, rather
than assuming the historical non-streaming 38-second case applies.
