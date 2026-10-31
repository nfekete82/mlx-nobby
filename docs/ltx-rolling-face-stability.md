# LTX Rolling-Window: facial-detail stability (I2V pilot)

Scope: opt-in 10s / 24fps at 540p or 720p, on top of the portrait-aware rolling pilot.

## Changes

- Preserve decoded pixels with H.264 **CRF 0** and decoded audio with **ALAC**
  in every intermediate segment and 25-frame context. The initial pilot lowered
  CRF 17 to 10; the follow-up isolated codec test demonstrated remaining loss
  at CRF 10 and exact decoded-YUV preservation at CRF 0. The final MP4 receives
  one H.264 CRF 10 / AAC encode with explicit frame/sample clocks. There is no
  face smoothing, reshaping, sharpening or artificial retouching.
- For image-to-video only, when `identity_lock=true` (the existing default),
  prepend short, positive continuity guidance to the **initial** I2V prompt
  and a context-specific guidance prompt to each native Extend step.
  Text-to-video and explicit `identity_lock=false` do not receive guidance.
- The native Extend CLI does **not** receive the original photo as a new image
  anchor: this is **soft prompt guidance**, not a guaranteed Identity Lock.
  The guidance preserves the request and does not suppress natural blinking.
- Bump rolling checkpoint fingerprint conditioning version to 3 and include
  transport codec settings. Old
  checkpoint combinations must fail closed rather than mixing encoding /
  conditioning strategies after a restart.
- Persist `rolling_identity_prompt_guidance` as a boolean in job state and
  final media metadata; keep user photos and prompts out of memory telemetry.

## How to test on the M5 Max

1. Confirm the video service is idle; don't restart during an active render.
2. Run `python3 -m pytest -q tests/test_video_rolling.py tests/test_video_segmented.py`
   and `node tests/test_video_job.mjs`.
3. Load the *same portrait* and *same prompt* as the previous 540p trial.
   Choose explicit **Rolling-Window-Test**, 10 seconds, **Standard 720p**,
   **portrait 9:16** and the same seed. Keep a fixed camera and natural
   subtle motion in the prompt. This preserves A/B comparability except for
   resolution / new facial-guidance conditioning.
4. Inspect eyes/pupils/eyelids at 0, 3, 5.9, 6.1, 7.9, 8.1, 9.9 s.
   Watch for drifting facial geometry, unnatural blinking, appearance
   changes at stitches, audio and memory pressure.
5. If needed, rerender **with `identity_lock=false`** for a controlled
   within-resolution prompt A/B test. Don't assume stronger prompt guidance
   is always better.
6. Review stage RAM/Swap telemetry from the existing 720p pilot.

## Limitations

- The prompt can reduce drift but cannot enforce facial identity, fix a
  fundamental model limitation or guarantee detailed eyes at 720p.
- Lossless intermediates preserve already decoded YUV pixels; they cannot
  reconstruct detail absent in the model's source frames.
- No biometric recognition, extra generation model loads or external
  inference service is introduced. The separate offline benchmark can use
  Apple Vision CPU landmarks at sparse samples. No 1080p Rolling Extend enabled.
- See the [reproducible benchmark](LTX_VIDEO_QUALITY_BENCHMARK.md) and
  [measured A/B report](LTX_QUALITY_REPORT_2026-10-31.md) for actual GPU results
  and remaining visual acceptance limits. Rolling remains opt-in.
