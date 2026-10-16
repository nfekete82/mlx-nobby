# MLX-Nobby 1.16.0 – Local Media Studio workflows

## Bild → Video or Talking Photo

In **Bibliothek**, choose any generated image, then either:
- **Talking Photo**: the existing Talking Photo dialog opens with the original PNG preselected. Enter text, choose engine and voice, then start the job.
- **Als Video**: the original PNG is attached to the active chat and the composer is prefilled with an editable image-to-video prompt. **No generation job is automatically started.** Send the prompt only after reviewing the video settings; the existing local video generator and resource guard are reused.

The image is loaded through the canonical Library media URL. Invalid/oversized files are rejected by the existing attachment contracts. No secondary inference service, new model weights or duplicate media exports.

## Verified local source lineage

After a completed Talking Photo or chat video job, the browser posts the source image and output video IDs to `POST /api/library/workflows/links`. The agent verifies both files really exist in their managed locations and are not symlinks, path traversal, empty files or acceptance fixtures. Accepted links are idempotently saved in the local atomic JSON file `~/.config/mlx-web/media-lifecycle/workflow-links.json`.

The media gallery fetches `GET /api/library/workflows`. A derived video shows **Ausgangsbild anzeigen** to jump back to the source image. A source image displays the number of linked derived videos. These are **metadata links only**; existing source/output files are never copied, moved or otherwise modified.

A user may still generate multiple outputs from the same source. Each output can have only one source; accidental reassignment is rejected. Deleting an image or video through the gallery removes the corresponding stale links but does **not** delete any other linked media. Deleted files cannot be recovered from history. Missing files are never exposed as valid links.

The optional link POST can fail without blocking video playback. If a browser closes before a job completes, the lineage association is best-effort: Talking Photo remembers a source in session storage for the active tab; video chat stores source metadata in the session and retries linkage when a completed session is resumed. There is no claim that all previously generated media have provenance.

## Release acceptance

1. Verify Library 3.0 search, favorites, collections and delete still work.
2. Use **Als Video** on a Library image: confirm attachment and editable prefilled prompt; confirm no job starts without sending.
3. Generate a real local video; verify it is present and linked to the source. Repeat with Talking Photo.
4. Refresh/restart the Agent and Docker web: verify source references persist, thumbnails still load, and no duplicate images/videos exist.
5. Verify source deletion removes only the link, not a derived video.
6. Pass Python tests, JS/i18n audit, Docker and Chromium browser acceptance on the feature branch.
7. Confirm VERSION, README, changelog, cache revisions and real Apple Silicon GPU workflow prior to release tagging.
