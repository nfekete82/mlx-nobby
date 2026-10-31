# LTX I2V facial text guidance: off / minimal / full

## Why

Native face crops from the October 31 causal experiment showed unnatural
long eyelid-closure windows already in the first 6-second I2V segment.
By turning off the previous automatically prepended text, the test
reduced the measured heuristic windows from 41 to 20 frames and
21 to 7 frames. This is a **single-image/single-seed** observation, not
general facial-quality acceptance. Codec CRF 0 did not fix the issue.
Neither latent carry nor face restoration is warranted from this evidence.

## New explicit request option

`video_options.face_guidance` (also accepted by the video service payload):

| Value | Effective prompt behavior |
| --- | --- |
| absent / `null` | Existing behavior: legacy `identity_lock=true` uses full face prompts for Rolling I2V; false uses the original prompt only |
| `"off"` | Original prompt only; **the first-frame image is still supplied** |
| `"minimal"` | Short positive guidance for natural identity, blinking and facial expressions; original prompt preserved |
| `"full"` | Existing longer descriptive face prompts; original prompt preserved |

The explicit value is **independent** of `identity_lock` in Rolling I2V.
In segmented 9/30/60s videos, `identity_lock` continues to control its
existing native keyframe-guide behavior. The new text option is rejected
there, as well as in T2V, multi-I2V and unsupported durations.

The browser offers the selector only when a managed source photo is
present and either the 10s Rolling-Window-Test or the 6s/720p standard
I2V probe is selected. The default is **Bisheriges Verhalten** and
does not send the new option. No permanent quality/default change.

## Six-second causal probe

To avoid paying for three stages when the defect occurs in the initial
segment, the existing direct native 6s/720p I2V path accepts
`face_guidance` explicitly. The service prefixes the selected **initial**
guidance and calls the existing provider. No Extend, extra model or
new inference parameters are added. With `face_guidance=off`, the
original prompt is passed through without modification. Without the
option the direct 6s I2V remains completely unchanged.

For a controlled test use the same original PNG, same seed (e.g. 0),
same user prompt, 720p (704x1280 portrait), 24fps and native
distilled 8+3 steps. Compare **off** against **minimal**, optionally
**full**, using the new face-analysis benchmark and raw native crops
at 0–6 seconds. A shorter low-aperture window is not automatically
better if blinking is unnaturally rapid or eye/pupil geometry degrades.

At least two matched seeds and visual human review should precede
any default promotion. There is **no automatic GPU generation** in
this code-only PR, and no claim of improved eye quality from tests
alone. GPU generation must honor the existing memory gates.

## Checkpoints / backward compatibility

- `face_guidance=None` is ignored by rolling, segmented and
  accumulated-long fingerprint calculations so old default checkpoints
  retain their hashes.
- Explicit `off`, `minimal`, `full` values are included in the
  rolling fingerprint to prohibit cross-mode continuation.
- Service resume preflight normalizes the absent legacy option to
  `None` only; settings mismatches are rejected.
- Rolling MP4 metadata reports `rolling_face_guidance_mode` plus
  the existing boolean guidance field, without changing user prompts.

## Verification

```bash
python3 -m pytest -q tests/test_video_rolling.py tests/test_video_segmented.py tests/test_i2v_conditioning_experiment.py
node tests/test_video_job.mjs
```

No default mode, model weights, pinned runtime, processing resolution,
RAM policy or real media files have been changed.
