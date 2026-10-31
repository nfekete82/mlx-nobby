# LTX-2.5 rolling facial quality: measured engineering report

Actual test date: **2026-10-31, Europe/Berlin (CET)**. Video work started after
local midnight; timestamps in raw telemetry use Unix/UTC. Hardware: Apple M5
Max, 48 GiB unified memory. Feature branch
`feat/ltx-rolling-face-stability-20261030`, draft
[PR #389](https://github.com/nfekete82/mlx-nobby/pull/389).

## Signal path and causes

1. **Original and scaling:** recovered the same managed 1097×1434 PNG as the
   previous successful job `3be75f703c82ec12116bedc0`. Its original prompt and
   seed 0 were recovered from persisted job metadata. The old 1024×576 landscape
   output has large side bars and a smaller face. It is historical evidence,
   not a controlled baseline for a portrait result. Both new runs use the native
   720p profile's actual **704×1280** canvas, 24 FPS, `contain`, without cropping
   or stretching the original. This grid-compatible profile approximates 9:16;
   it is not a literal 720×1280 raster. The preparation writes a lossless PNG.
2. **Prompt and initial conditioning:** both new runs use the same user prompt,
   short existing positive I2V facial guidance, seed, original source and
   8+3 distilled steps. No negative prompt, face restoration or stronger pose
   anchor was added. Native checkpoint conditioning deliberately preprocesses
   the still with H.264 CRF 18 and bilinear resizing, then starts generation at
   half spatial resolution before 2× refinement. Detail absent after those
   model operations cannot be recovered by reducing later encoding loss.
3. **Native generation:** installed `dgrauet/ltx-2.5-mlx-q4`, LTX-2.5 22B
   distilled, int4 transformer/text-encoder linear weights, group size 64;
   native MLX/Metal runtime 0.18.0 at
   `b82b97e3d000e01361f8cfcb745244b15b89a521`. The installed launchd configuration
   explicitly selects this staged runtime for initial generation and extension.
   The separate older stable checkout was not used. Both distilled stages use
   native LTX-2.5 ancestral schedules; CFG is not applicable. The runtime itself
   writes video at H.264 CRF 18. No speculative CLI parameters were introduced.
4. **Temporal carry:** only 25 frames and matching audio enter each 48-frame
   extension. In native `extend_distilled.py`, source pixels are VAE-encoded at
   half and full resolution, four latent context frames are pinned in both
   stages, source and appended latents are combined, then decoded. The next
   extension therefore sees generated, re-encoded/reconstructed detail rather
   than the original photo. This is an architectural drift mechanism inferred
   from runtime source; its isolated visual contribution was not measured by a
   separate VAE-only GPU experiment.
5. **Transport loss, experimentally isolated:** trimming the same historical
   25-frame tail at the former CRF 10 gives native decoded-YUV SSIM **0.998028**
   against its exact input frames; CRF 0 gives **1.000000** on every plane.
   The synthetic regression additionally compares all decoded YUV bytes for
   exact equality. This proves an avoidable codec loss; it does not prove that
   codec loss was the main cause of eye deformation. Tail sizes were 410,276 B
   versus 2,057,930 B for this example. Temporary disk use rises, not GPU window
   size or denoising token count.
6. **Stitching and sound:** the old AAC/MP4 concat starts video at 0.021322 s and
   audio at zero. New assembly trims each decoded segment to exactly 2,000 audio
   samples per frame, resets independent clocks and concatenates them before a
   single AAC/H.264 output encode. The inclusive initial frame gives 241 total
   frames, so video stream duration is 10.041667 s. Exact joins are frames
   144→145 and 192→193; the old mux offset places them at 6.062988/8.062988 s.
   Duration/offset checks do not establish spoken lip sync.
7. **Playback:** final encoding remains browser-compatible H.264 yuv420p/AAC
   with faststart. There is no smoothing, synthetic interpolation, frame
   blending, eye correction, face reshaping or color correction.

## Implemented changes

- Lossless decoded-YUV intermediate H.264 CRF 0 and lossless ALAC transport;
  final H.264 CRF 10/AAC encoding occurs once after sample/frame-clock assembly.
- Checkpoint conditioning version 3 includes transport settings. Old or altered
  checkpoints are rejected rather than mixing strategies. Explicit user abort
  is not resumed; lifecycle/failure resume reuses only verified stages.
- Agent now forwards `identity_lock` and `identity_strength` from explicit
  video options; the existing native validation still applies. Rolling uses
  the lock flag for prompt guidance; the strength is relevant to the separate
  segmented image-guide mode and does not invent an Extend face-ID control.
- Offline bounded-memory quality benchmark, native review frames, original
  reference, local video players, exact seam windows, full-resolution duplicate
  hashes, timestamp checks, local SSIM/MAE/detail diagnostics, optional sparse
  CPU Apple Vision geometry/crops and explicit uncertainty labels.
- Read-only two-second macOS memory monitoring with a fixed deadline.
- Fixed a real macOS guardian startup race exposed by the candidate attempt.
  One of 50 isolated CPU starts initially showed only `(python3.11)` to `ps`.
  Registration now waits at most 0.5 s for the unpredictable ownership token;
  workload GO remains blocked until identity is confirmed. Failure and cleanup
  still fail closed. This change does not automatically retry generation jobs.

Native 0.18 **does** support optional image guides on appended frames. They are
pose-bearing guides, not facial embeddings; this integration intentionally does
not enable repeated original-photo anchors without a separate motion/memory
acceptance comparison. Existing comments/documentation were clarified.

## Tests and existing failures

See [machine-readable test evidence](ltx-quality-evidence/tests.json). Counts
below overlap; they are not a sum of unique tests.

| Suite | Result |
| --- | --- |
| Required rolling + segmented Python tests | **22 passed**, 0 failed |
| Expanded video/provider/API/resume/edit/telemetry suite | **135 passed**, 0 failed, 1 module skipped; 10 subtests passed |
| Guardian change + lifecycle/rolling/segmented/long-video | **76 passed**, 0 failed |
| Additional memory-budget and lifecycle suites | **35 passed**, 0 failed |
| Benchmark in existing image environment | **4 passed**, 0 failed |
| New desktop/mobile rolling browser tests | **2 passed**, 0 failed |
| Required JavaScript video job test | passed |
| JavaScript player preservation / edit recovery | **2 / 5 passed**, 0 failed |

The skipped benchmark module has NumPy/SciPy dependencies absent from the test
venv; its four tests pass in the existing image venv. The initial system Python
has no pytest. Eleven expanded tests initially failed inside the execution
sandbox because `ps` was denied; the full unsandboxed rerun passed.

The old general browser acceptance has **6 passed test bodies and 6 teardown
errors**, all from shared `AgentFixture` returning HTTP 501 at
`GET /api/mlx/video/edit/jobs`; older local artifacts contain the same errors.
The new focused tests supply only that unrelated missing endpoint before
navigation and retain strict console/error checks. General tests-only discovery
still has **3 existing collection errors**: `KeyError: mlx_agent` and two
untracked LTX-lab tests importing missing `ltx_lab.telemetry`. Repository-root
discovery adds old artifact-source snapshots and yields 10 collection errors.
These unrelated files were left unchanged.

## Render accounting

- Baseline: job `cb7197efd8000d69bdcc6071`, source commit `f9fe5226`, completed,
  **429.194 s**, stage times 217.55 / 106.57 / 103.11 s.
- Candidate startup attempt: `173be32d6f2f2c5c4ce82d98`, commit `82009145`, failed
  **before inference** after 10.567 s; zero checkpoints and no video. Memory
  was normal, no swap growth, no surviving worker. It is recorded separately
  and is not counted as a successful model render.
- One bounded explicit continuation uses `resume_from` through the existing API,
  after the CPU reproduction and 76 passing regressions. There are no automatic
  GPU retry loops. The two-completed-video limit remains in force.

Paired candidate measurements and deployment status are appended after completion.

## Matched A/B result

The resumed candidate `cb0127c78f871c3878512788` completed successfully under
commit `feeb9b21`, producing `b6731ecfcbbf3114a32b5c01.mp4`. There were exactly
**two completed new full renders**, one pre-inference startup failure and one
bounded explicit continuation. No additional GPU generations were started.
Source SHA256, prompt SHA256, seed, model and recorded settings match between
baseline and candidate. Full numeric evidence:
[comparison](ltx-quality-evidence/comparison.json),
[model provenance](ltx-quality-evidence/model-provenance.json),
[isolated codec experiment](ltx-quality-evidence/codec-comparison.json).

| Measurement | Before | Candidate |
| --- | ---: | ---: |
| Actual dimensions / frames / FPS | 704×1280 / 241 / 24 | 704×1280 / 241 / 24 |
| Video start | 0.021322 s | **0 s** |
| Audio start | 0 s | **0 s** |
| Audio/video end difference | 0.000011 s | **0 s** |
| Container duration | 10.063 s | **10.041667 s** |
| Exact adjacent duplicates | 0 | 0 |
| PTS anomalies | 0 | 0 |
| Adjacent luma SSIM, median | 0.985924 | 0.986028 |
| Join 144→145 SSIM | 0.986860 | 0.987769 |
| Join 192→193 SSIM | 0.991580 | 0.991920 |
| Join 144→145 MAE | 1.274352 | 1.262120 |
| Join 192→193 MAE | 0.975267 | 0.989223 |
| Laplacian variance, median | 168.934830 | 169.735672 |
| Generation time | 429.194 s | 420.956 s |
| Stage times | 217.55 / 106.57 / 103.11 s | 209.97 / 103.81 / 103.34 s |
| MP4 bytes | 7,112,285 | 7,019,153 |

SSIM and MAE/detail diagnostics use an explicitly reported 282×512 analysis
raster for these portraits. Native pixels are retained for duplicate hashing,
review frames and face crops. The slight SSIM/detail changes are technical
observations, not a statistical or biometric quality acceptance. In particular,
the second join's MAE is slightly worse while SSIM is slightly better. A single
pair does not establish a general speed improvement either.

**Visual assessment from the native extracted frames and face crops:** the
person's broad appearance and continuous head pose are similar in both new
videos. No conspicuous facial reset is visible in either inspected exact join
pair. Fine eye asymmetry/eyelid and iris variation remains in both. The final
smile/mouth differs somewhat after the generated continuations. These samples
do **not** establish a substantial visible improvement in facial identity or
perfect eyes. Native original-image conditioning, half-resolution denoising
and repeated VAE reconstruction remain possible sources of lost facial detail.
No claim of complete natural-blink or spoken lip-sync acceptance is made from
sparse stills. Geometry measurements also vary with desired pose/expression and
are not ranked as an identity score.

The local, private HTML comparison includes original references, both players,
the historical video, native samples at requested times, actual timestamps,
face crops and exact join windows:
`artifacts/ltx-quality-20261031/comparison/index.html`.
Its media/landmark files are deliberately not pushed to GitHub. The nearest
frames at a requested absolute time can differ by one frame because the old
mux has a 21-ms offset; exact join comparisons always use the same frame indices.

## Memory, performance and playback

[Memory evidence](ltx-quality-evidence/memory-summary.json) distinguishes
complete candidate monitoring from late-only baseline monitoring. Stage
snapshots and job metadata are also retained in the comparison JSON.

- Baseline admission after the normal exclusive handoff: **84% available
  estimate**, 34.32 GiB headroom, swap 7.41 GiB. Stage-end swap decreased to
  **7.26 GiB**. The late monitor covers only the final 166 s: minimum available
  estimate 63%, minimum headroom 24.24 GiB, normal pressure. It must not be
  presented as a measured peak for the whole baseline.
- Candidate admission: **80% available estimate**, 32.40 GiB headroom, swap
  7.24 GiB. The two-second monitor collected **207 samples**, covering nearly
  the entire resumed job. During active work the minimum available estimate
  was **58%**, minimum headroom **21.84 GiB**, maximum swap 7.24 GiB;
  final swap **7.22 GiB**. All observed pressure readings were normal.
- The pre-inference failure had unchanged 7.24 GiB swap. Existing swap alone
  is not classified as critical by the established guard; growth and actual
  availability are checked. No guard was disabled or threshold relaxed.
- The native initial decoder reported peak Metal memory 14.30 GiB in its
  local log; this is a decoder/runtime observation, not whole-system RAM.
  System budget probes include availability estimates and are not exact
  resident accounting. Two-second sampling can miss shorter peaks.
- Real Chromium decoding through the production **8090 web API** passed for
  both MP4s: 704×1280, no media error, successful playback, all seven requested
  seeks reached their exact positions. The web video endpoint answered a
  1,024-byte range with HTTP **206**. See
  [baseline playback](ltx-quality-evidence/baseline-browser-playback.json) and
  [candidate playback](ltx-quality-evidence/candidate-browser-playback.json).
  An initial one-off plain HTTP file-server probe could not seek reliably;
  this was a diagnostic-server limitation. Acceptance uses the actual web API,
  not that result.

## Retained limitations and next step

Retain the changes for the explicit experimental rolling mode: exact transport
preservation and corrected container timing are demonstrated, the output plays,
and the memory-bounded 25-frame inference design remains intact. **Do not
promote to default or claim facial-stability acceptance from this single pair.**
The measured quality gain is modest; the requested clearly superior natural
face is not proven. No additional render is justified without another budget.

The next technically targeted experiment is a native **latent carry checkpoint**:
write the prior half/full-resolution video and audio carry latents to disk and
reuse them in the next window, avoiding video decode→VAE re-encode of generated
context. This is a proposed future experiment, not an implemented or proven
fix; it needs explicit native-interface work, memory bounds, checkpoint integrity
and another matched GPU comparison. Repeating the original-pose guide or adding
a heavy face model before proving its motion/memory tradeoff is not justified
by the present evidence.

Implementation commits: `82009145` (transport/clocks/benchmark/options/tests),
`feeb9b21` (confirmed guardian startup race and bounded identity wait).
Final evidence/documentation is committed on the same branch and linked from
[PR #389](https://github.com/nfekete82/mlx-nobby/pull/389); no merge to `main`.


## Local rollout and preservation

The video service was restarted only while idle after passing the relevant
regressions; the resumed successful candidate exercised the deployed code.
The Agent was restarted only after both video health and queue/lease diagnostics
showed no active or waiting work, to load the video-options whitelist change.
Final health: video ready with no active job, web `ok`, Agent queue 0 active /
0 waiting. See [deployment evidence](ltx-quality-evidence/deployment.json).
Frontend assets did not change, so the existing Docker web container needed no
rebuild. Rolling remains an explicit opt-in. There was no merge or default-mode
promotion.

Existing untracked project/lab/benchmark files were preserved. Initial Git status
and the empty tracked-change patch were saved in `/private/tmp`; the existing
37 untracked top-level paths were also archived without deleting them at
`/private/tmp/mlx-nobby-existing-untracked-20261031.tar.gz` (255,829,119 bytes).
Private originals and generated media remain local. Newly generated private
reports and videos under `artifacts/ltx-quality-20261031/` are Git-ignored;
only measurements, code, tests and documentation are committed.
