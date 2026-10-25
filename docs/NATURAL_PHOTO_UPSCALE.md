# Natural Photo Upscale (Oct 2026)

## Motivation

The preexisting **2× Photo** and **4× Photo** options both called
`realesrgan-x4plus` with different output scales. The neural restoration
can over-smooth skin and produce a polished / artificial appearance.
Higher scale alone does not improve fidelity.

## UI choices

- **Foto natürlich · 2× (recommended, first option)**:
  Real-ESRGAN 2×, then 55% neural output + 45% original image upscaled
  with Lanczos. This favors keeping the original appearance.
- **Foto natürlich · 4×**: Real-ESRGAN 4×, 60% neural + 40% source.
- **Foto scharf · 4×**: Real-ESRGAN 4×, 82% neural + 18% source,
  followed by a mild thresholded unsharp mask. This can produce halos on
  high-contrast edges; use deliberately, not as default.
- **Illustration · 4×**: existing anime weights without new finishing.

The legacy `photo-2x` and `photo-4x` preset names still work for old
image jobs and API clients and produce **unchanged** results. The direct
Image Service API preserves its legacy default for compatibility, while
the chat UI defaults to `photo-natural-2x`.

## Implementation and safety

- Only the existing local `realesrgan-x4plus` and
  `realesrgan-x4plus-anime` weights are required.
- Image finishing uses the already-installed Pillow library, and writes
  the final PNG atomically before the existing WEBP finalizer and metadata
  publish. Input files are never overwritten.
- Source resolution, job admission, cancellation, progress, web routing and
  model loading are unchanged. Legacy illustration/upscale paths bypass
  the new finishing pass.
- Source transparency is preserved. No external downloads, new model
  server, model switching or always-on face restoration.
- **Quality tradeoff:** blending reduces neural overprocessing but does
  *not* recover genuine details lost in the original. Finishing also
  needs additional temporary image memory, particularly for large 4×
  outputs. Use 2× natural as the everyday default.

## Validation

```sh
./scripts/mlx test-quick tests/test_natural_photo_upscale.py \
  tests/test_image_upscale_chat_action.py
node --test tests/test_image_edit.mjs
```

For a practical A/B test, run the *same photo* through **Foto natürlich
2×** and **Foto scharf 4×** and inspect skin, hair, fabric textures,
color and edges at 100% zoom. The result is judged on the Mac with the
installed model; unit tests cannot claim superior visual quality.
