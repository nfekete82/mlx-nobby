# Engineering activation and native inference audit — 2026-10-27

Follow-up to the [first-pass audit](ENGINEERING_AUDIT_2026-10-27.md).
Baseline Git revision: `2adfa81`. The original 15 changed/new files were
reviewed against the previous implementation and snapshotted before further
changes. All their changes belonged to this audit. Existing untracked LTX code,
tests, reports and benchmark captures were excluded from edits and staging.

## Log growth and rotation

The approximately 9.9 GB Agent log consisted predominantly of uvicorn HTTP
access records. Only three bounded 1 MiB samples were inspected, with aggregate
route/status counts saved; private log lines were not exported. In the middle
sample, 14,764 of 14,769 lines were workspace requests. This is consistent with
the historic request loop documented in `PERFORMANCE_AUDIT.md`, whose frontend
fix predates this round. Current output still lacked any retention policy.

`agent/log_rotation.py` now captures Python, native and inherited subprocess
stdout/stderr at the file-descriptor level. It preserves the actual service
PID and uvicorn signal handling. The launchd template invokes
`scripts/agent-server.py`; launchd's own output descriptors point to `/dev/null`
so they cannot continue writing into renamed log inodes.

Each of `agent.log` and `agent-error.log` has a **16 MiB** byte cap and **three
numbered backups**: at most 128 MiB combined, excluding legacy archives and
empty writer-lock files. A single writer lock prevents competing rotations.
An existing oversized log is renamed, never copied or truncated. The original
9,911,776,800-byte log is preserved as `agent.log.legacy-<timestamp>` and is
deliberately outside automatic deletion; it still occupies disk space.
Disk-write failures drain the bounded pipe rather than deadlocking inference.
Fresh log files use mode 0600. No access-log suppression or user-log deletion
was introduced.

## Upload saturation and memory bounds

The first pass moved PDF extraction/indexing and transcription forwarding off
the event loop. A saturation regression reproduced a second problem: slow
uploads could exhaust Starlette's shared worker limiter and starve sync health
handlers.

`backend/upload_work.py` now supplies **two dedicated workers** and admits only
two upload operations before reading their full bounded payloads. Queued large
uploads remain spooled rather than accumulating additional 250 MiB byte strings
while waiting for external STT or PDF processing. The normal API worker pool
remains available. This bounds active upload operations, not all Python memory:
decoded PDFs, multipart processing and response bodies still have their own
costs. An in-flight blocking operation finishes or reaches its existing timeout;
offloading does not forcibly interrupt a Python worker.

The previous bounded log readers, 32 MiB buffered audio-cache budget and shared
cancellable Real-ESRGAN pipe reader remain in place. No new dependencies,
frameworks, model parameters, admission thresholds or scheduling system were added.

## Integration and native validation

- **154 targeted Python tests**, 20 additional subtests and **11 JavaScript
  tests** passed in the final relevant group. Coverage includes rotation,
  shared-pool starvation versus isolated workers, queued cancellation, upload
  contracts, runtime budgets/leases, pipe deadlines/cleanup and speech caching.
  Syntax, plist and diff checks passed; the existing TestClient/httpx deprecation
  warning remains.
- A real isolated uvicorn instance retained its service PID, rotated a roughly
  19 MiB output burst at exactly 16 MiB, and completed graceful shutdown. Tests
  also cover inherited child output, sparse oversized legacy logs, retention,
  competing writers and disk-write failure without pipe blockage.
- The built production web image passed actual HTTP PDF parsing/index-contract,
  image conversion and six concurrent STT forwarding requests against a local
  synthetic Agent fixture. Maximum active STT calls was **2**; five health
  responses during saturation took **1.08–3.65 ms**. No production data volume
  was mounted in these fixture containers.
- The installed native Real-ESRGAN binary processed a synthetic **96×64 →
  192×128** image through the changed service function in **0.513 s**. A second
  actual invocation cancelled in **0.250 s**. Child processes were reaped,
  pipes closed and process callbacks cleared. System swap changed by approximately
  **+0.09 GiB**, below the existing 0.5 GiB growth guard. This is a smoke test,
  not a media quality or throughput benchmark.

## Native before/after inference measurements

The same already loaded **Qwen3.8-27B, 6-bit** model and native runtime process
were used before and after deployment. MLX 0.32.2 / MLX-VLM 0.6.17; prefill step
1024; continuous batching enabled with CLI maximum 2 sequences. Sampling was
temperature 0, a 96-token output cap and disabled thinking. Each of two fixed
synthetic workloads ran once as warm-up and three measured times, both directly
and through the stateless OpenAI gateway: **32 completed GPU requests** total.
All measured answers contained 86 completion tokens. Prompts contained 25 or
1,188 tokens.

Model/settings fingerprints, request hashes and response hashes matched between
phases. Prompt-prefix caches were not reset, models were not switched/unloaded,
and no experimental profile was enabled. The script checks idle services and
queues before requests, takes the existing lease for direct native calls, and
monitors the existing pressure/swap-growth limits during generation.

| Median metric | Before | After |
| --- | ---: | ---: |
| Native short TTFT | 181.7 ms | 184.4 ms |
| Native 1,188-token TTFT | 1,558.4 ms | 1,620.3 ms |
| Native 1,188-token prefill, server-reported | 1,489.6 ms | 1,542.4 ms |
| Native short decode | 23.71 tokens/s | 23.33 tokens/s |
| Native 1,188-token decode | 23.42 tokens/s | 23.50 tokens/s |
| Gateway short TTFT | 230.4 ms | 230.2 ms |
| Gateway 1,188-token TTFT | 1,692.2 ms | 1,737.6 ms |

TTFT means first nonempty assistant content/reasoning, excluding role headers and
heartbeats. Prefill/decode fields come from native server timings. Three samples
are descriptive, not a significance test. **No inference speedup was demonstrated.**
The resource/reliability fixes are retained for their independently verified
bounds and behavior; they do not claim faster Metal kernels.

Full-system free-memory estimates stayed at least 35% during the baseline and
36% during the post-deployment run. Existing swap was 9.10 GiB before and
8.88 GiB after the overall sequence; the reduction is not attributed to these
changes. Reported MLX peak reached 24.653 GB in both phases. That is the runtime's
cumulative allocator peak, not a reset per-request or host-wide measurement.

Reproduce on an idle stack with the existing test environment:

```sh
test-venv/bin/python scripts/benchmark-inference-audit.py \
  --phase before --samples 3 --gateway --output /tmp/nobby-before.json
# Apply only a separately reviewed change, then repeat with --phase after
# and a different output path. Never mix models/settings across a comparison.
```

## Deeper inference findings and decisions

- Installed `mlx_vlm.server.app.get_cached_model()` keys resources by model,
  adapter, model kind and runtime settings. Cache hits return the same model,
  processor/tokenizer and generation worker; no repository change to repeated
  initialization was justified. First requests in both runs were slower
  (2.34/2.71 s TTFT) and were excluded as warm-ups; they do not measure a cold
  model load or prove repeated loading.
- KV state is used inside generation. **Cross-request prefix reuse** was absent:
  `cache_n=0` on every measured request, APC disabled, no KV quantization or
  explicit `max_kv_size` configured. The advertised context limit is 262,144,
  not a tested safe RAM budget. Short tests cannot certify maximum-context memory.
- Active draft model/kind and returned draft counters were null. The configured
  but inactive DFlash path is not evidence that speculative decoding or MTP is
  running. No draft, KV quantization or APC/Hybrid activation was attempted;
  the documented quality/swap acceptance HOLD remains applicable.
- Nobby's cross-service lease intentionally serializes coordinated heavy work,
  despite the backend's two-sequence capability. Removing it to increase
  concurrency would compromise the existing unified-memory policy. Other services
  stayed online, but simultaneous heavyweight generation was not stress-tested.
- No model-switch/cold-reload benchmark was forced on this production stack with
  approximately 9 GiB of existing swap. The unchanged native PID, loaded model
  and settings were verified after activation. Destructive cache resets,
  long-context saturation and full media/release acceptance remain outside this
  bounded run.

## Activation, rollback and Git scope

After a fresh idle check and while holding the shared maintenance lease, only
the Agent, idle image service and web container were restarted/recreated. No
active or queued jobs were observed or cancelled. This was an idle-window
deployment, not a zero-downtime guarantee. The chat process and selected model
were preserved; web data mounts matched their prior definitions. All eight
supporting service probes returned HTTP 200; native chat readiness was verified
separately. Both live log APIs returned bounded results in **3.4–4.3 ms**.

The web candidate is tagged `mlx-web:engineering-candidate-20261027`, with build
identity `engineering-20261027`. This development activation is not a release
or an all-service Git-revision consistency certification.

Private, ignored evidence and rollback material is in
`artifacts/engineering-20261027/`: initial-source hashes, baseline source,
previous LaunchAgent plist, retained old image tag, container mount manifest,
health results and content-free benchmark JSON. The rollback image is
`mlx-web:engineering-rollback-20261027`. The local rollback procedure is:

```sh
test-venv/bin/python artifacts/engineering-20261027/activate.py rollback
```

It requires an idle stack, verifies candidate source hashes before restoring
the six affected runtime/frontend files, restores the previous Agent plist
and web image, and restarts the idle image service. It refuses to overwrite
subsequent source edits. Rollback would change those working-tree files; it
does not reset Git commits or remove the legacy log/data volumes. Do not delete
the ignored checkpoint or old image until the maintenance window is closed.

The commit contains only the original 15 audit files plus `.gitignore`,
`agent/log_rotation.py`, `backend/upload_work.py`, the Agent launchd template,
`scripts/agent-server.py`, `scripts/benchmark-inference-audit.py`,
`tests/test_log_rotation.py` and this follow-up report: **23 files** total.
Existing user-owned untracked work is excluded. No push or release is performed.
