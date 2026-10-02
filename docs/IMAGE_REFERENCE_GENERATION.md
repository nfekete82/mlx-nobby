# Local person reference images

Chat distinguishes text-to-image, ordinary image editing and
`image_reference_generate`. Explicit German/English requests for the same person
or face, or a person resembling the reference, use the last intent. It executes
through the existing `edit` job and provider pipeline, not through text-to-image.
Questions, prompt-writing and video requests retain priority. An unrelated
text-to-image request does not consume an attached reference.

## Source and model selection

A single image attached to the current turn takes priority. Otherwise an
explicitly active workspace image artifact can be used. Ambiguous current
attachments require source selection; a historical fallback is not accepted.
A missing reference produces a clarification instead of a text-to-image job.
An explicitly active reference result supports short scene follow-ups such as
“Jetzt draußen im Regen”. Such follow-ups continue using its original reference.

The existing edit-model resolver prefers the configured compatible model, then
available enabled models with `image_edit`. Availability and the MFLUX CLI/weight
contracts remain authoritative. If no compatible local model is available,
the job fails with a readable reference-model error. No T2I fallback or automatic
model download is introduced.

## Render contract

`same_identity` adds a short identity-preservation instruction; `resemblance`
asks for recognizable visual resemblance. Both retain the user's scene request
and structured reference semantics after translation. No unsupported identity
strength parameter is sent. `source_path` reaches the existing Qwen
`--image-paths` argument. A new output is created; the source is never overwritten.
Qwen's supported target-canvas dimensions are normalized to the requested aspect
ratio and quality profile. Other providers retain their existing source-size
policy. MFLUX's advertised CLI flags are still checked before execution.

Result artifacts carry `semantic_operation=reference_generate`,
`reference_used`, `reference_mode`, `reference_relation` (the same semantic value),
`reference_artifact_id`, and the normal
model/provider/quality/dimensions/steps/guidance/seed metadata. The existing local
source path supports regeneration; it is not displayed in normal result cards.
No image bodies or base64 data are added to artifact metadata.

## Gallery and regeneration

Reference batches reuse the private frozen Edit configuration: source, model,
provider, effective prompt, quality, dimensions, steps and guidance stay fixed.
Only seeds change. Slots remain normal sequential Edit jobs under the existing
runtime coordinator and service lock. Retry preserves successful slots and their
planned seeds. The source job remains unchanged; group decoration of the base
image uses a response copy. Ordinary T2I batches keep their existing behavior.

“Regenerate” preserves the original source and reference mode while requesting a
new seed. Result cards show “Reference image used” and the selected reference
mode; pending jobs use a reference-processing label. Local generative models can
change facial details. Identity is not guaranteed and no face-similarity service
or additional face model is used.

## Local verification

Attach one person photo, request “Kannst du ein Bild erstellen, das dieser Person
ähnelt?”, choose quality, and check the result's provider and reference indicator.
Repeat with “Erstelle ein neues Bild derselben Person in einem modernen Büro”.
Try gallery counts 3/6, regeneration and a short follow-up. With no compatible
local edit model, expect the reference-model error and an unchanged source.
