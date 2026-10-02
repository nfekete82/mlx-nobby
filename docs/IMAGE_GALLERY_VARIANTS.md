# Canonical image galleries

The image-count picker waits for the first completed image, then sends one
`POST /api/mlx/image-jobs/variants` request with its native
`generation_job_id`, the chosen count and `include_base=true`. The artifact's
effective settings are authoritative. Picker dimensions and quality are not
reapplied to subsequent slots. This prevents the old smaller-resolution
regeneration path and repeated prompt/model resolution.

The artifact's “3× Regenerate” action also uses the canonical batch, with
`include_base=false`. Ordinary single-image Regenerate keeps its existing path.
Artifacts without a valid native job ID, or with `variants_available=false`,
have disabled variant actions; programmatic requests show a localized DE/EN
notice. No job ID is inferred from an image ID or historical chat content.

## Groups, retry and cancellation

The server assigns `variant_group_id`, `variant_index` and `variant_count`.
The gallery orders slots by index and can display a partly restored group with
missing placeholders. Retry sends the same group ID and updates existing
messages; the backend renders only failed, interrupted or invalid-file slots.
Completed images and planned seeds remain unchanged, including after restart.
Restored terminal groups are checked against the server once, so missing image
files become failed slots and can be retried instead of remaining broken previews.

“Cancel variants” uses the existing group cancellation endpoint with the bound
chat ID and revision. Completed slots remain available. Accepted cancellation
stops pending slot presentation; delayed running responses cannot undo it.
The backend keeps the render lock until the active provider has stopped.

Each response is checked against the current chat, revision and request. A
superseded new batch is cancelled through its group endpoint. Old count-picker
requests cannot delete newer selections. Delayed polls cannot overwrite newer
retry/cancellation state or an explicitly selected gallery image.

## Reference images

Reference Edit jobs from Image Reference Generation use the same batch contract.
The original reference, semantic mode/relation, frozen model/provider, effective
prompt, dimensions and quality settings stay fixed. Only seeds vary; execution
is sequential. No text-to-image fallback is introduced.

## Verification

The count-picker, regenerate and gallery DOM tests exercise one batch request,
3/6 slots, group ordering, reference jobs, selective retry presentation,
cancellation, legacy notices and stale response guards. Image runtime/variant
tests verify the actual frozen provider inputs, file validity, restart recovery
and cancellation. No extra models or dependencies are required.
