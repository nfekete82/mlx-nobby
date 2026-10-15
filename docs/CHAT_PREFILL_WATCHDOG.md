# Chat prefill watchdog — measured 27B latency

## Problem and evidence

The local Performance Observatory recorded one complete `chat.stream` call
with a **28,630.636 ms first-token delay**, **5.468 ms upstream HTTP connect**,
**6.791 ms queue wait**, and 24.57 output tokens/s. The main model server
answered `GET /v1/models` in ~37 ms when checked subsequently, and the
runtime-reliability endpoint reported no active lease or waiting task.
Those are observations at different moments; they do *not* prove the
cause of the older timeout or the generation delay.

At the former **30-second** ordinary text first-byte watchdog default,
a healthy model doing long prompt prefill or a cold first request could
reach the recovery path before returning a token.

## This change

- The ordinary text first-byte deadline defaults to **60 seconds**.
  `MLX_CHAT_FIRST_BYTE_TIMEOUT` can override the value (minimum 10 s).
  Current-information search retains its independently configured 90 s
  default. Vision retains its independently configured 60 s default.
- A first-byte deadline remains **absolute**, so an actual hung runtime
  still reaches bounded recovery. Existing protection against restarting
  active image/video/coding tools and 60 s restart cooldown are unchanged.
- When automatic recovery is rejected, the SSE error now identifies
  **cooldown (HTTP 429)**, **protected active workload (HTTP 409)** or
  **unknown recovery failure**. Raw upstream error detail (which may
  contain sensitive paths or tokens) is never repeated to the user.
- No automatic restart, retry or memory-guard policy was relaxed.

## Not a speedup

**This does not make the 28.6 s prefill faster.** It removes a likely
false timeout boundary and improves observability. Further investigation
requires back-to-back cold/warm `chat.stream` TTFTs, context/prompt
size and actual model health while a slow request occurs. Router
latency was 894 ms in the same sample, and no active lease was visible
when diagnostics were inspected. One sample is insufficient to change
model settings or DFlash2.

## Check after local update

```sh
cd ~/mlx-web
python3 -m pytest -q tests/test_runtime_reliability.py
docker compose up -d --build --no-deps mlx-web
```

Look for the two different states in
`GET http://127.0.0.1:8010/api/runtime/reliability`:
`lease.active_workload` during a slow request and `recovery` if a
timeout occurred. The browser-facing reliability endpoint is served by
the **Docker web backend**; a separate restart of the native MLX
language model is not necessary for this particular patch.
