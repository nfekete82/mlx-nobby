# MLX-Nobby 1.15.0 · Media Library 3.0

## Navigation

The **Dateien & Jobs** action is moved into the expanded sidebar **System & Tools** group (with Help, System Info, Settings). It retains the original element ID and click handler. The collapsed desktop rail retains its Files/Jobs quick action.

## Organizing locally generated media

- Tap the **☆ / ★** button on any image, video or Talking Photo to toggle favorites.
- Use the **Sammlung** filter to switch between All media, Favorites and named collections.
- **+ Sammlung** creates a named local collection; duplicate names are rejected case-insensitively. Delete collection only deletes collection metadata, **not** media.
- Select any cards using checkboxes or **Sichtbare auswählen**. The bulk toolbar can mark selected items as favorites, add/remove them from a target collection, clear selection or permanently delete selected files with an explicit confirmation.
- Selected assets persist across filter changes while the panel remains open; stale selections are pruned on refresh.
- Favorite/collection assignment promotes selected temporary media to persistent local storage so the normal temporary TTL does not silently remove it. Unfavoriting/removing from a collection does not re-enable TTL; use explicit library delete to remove unwanted media.

## Persistence and security

Organization metadata resides in `~/.config/mlx-web/media-lifecycle/collections.json`. No original PNG or MP4 file is copied or moved. Writes are atomic JSON file replacements under the existing lifecycle lock. Collections use random opaque 16-hex-character IDs; names are 1–60 characters. Limits: 100 collections, 5,000 entries per collection/favorites and at most 100 items per mutation request. UI can split larger selections into batches.

Every POST validates asset kind, canonical generated-media ID, expected managed media root, regular nonsymlink file, nonzero size and non-acceptance ownership. Raw file paths and prompts are not exposed. Deleting individual or all media from the library removes their favorite/collection metadata. Older stale metadata is omitted from GET responses automatically. Deleting a *collection* alone never deletes the originals. There is no cloud sync.

## API

- `GET /api/library/organize`: `{version, favorites: ["kind:id"], collections: [{id,name,items}]}`.
- `POST /api/library/organize/collections`: `{"name":"My collection"}`.
- `DELETE /api/library/organize/collections/{id}`: metadata-only delete.
- `POST /api/library/organize/batch`: `{"items":[{"kind":"image","id":"..."}],"operation":"favorite|unfavorite|add_collection|remove_collection","collection_id":"..."}`.

All routes use the existing local agent's authentication and host isolation.

## Acceptance checklist

1. Verify System & Tools expands to show Dateien & Jobs, and the original click still opens the jobs panel (desktop/mobile).
2. Create a favorite and two collections; add image + Talking Photo in one multiselection.
3. Refresh/restart the agent; verify stars, membership and filters persisted without duplicate PNG/MP4 files.
4. Remove a collection; confirm its media remains in Bibliothek. Delete selected media with confirmation; verify removal and metadata cleanup.
5. Run full macOS Python and JS tests, Docker validation and Chromium desktop/mobile acceptance on PR #258.
6. Verify VERSION, README/changelog headings and cache revisions match v1.15.0. No release tag until checks and real local acceptance are complete.
