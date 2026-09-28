# Nobby Memory Manager

The Memory Manager is available under **Settings → Memory** and manages the local long-term memory introduced with Nobby Memory v1.

## Features

- Search all saved memories.
- Filter by active, pinned, or disabled entries.
- Add new memories manually.
- Edit memory text, category, and importance.
- Pin or unpin important memories.
- Enable or disable individual memories without deleting them.
- Permanently delete memories.

The UI talks only to the local web backend (`/api/mlx/memory`), which proxies the existing agent memory API. Memory data remains in the local SQLite database at `~/.config/mlx-web/memory.db`.

The Memory Manager script is injected into the existing chat/settings HTML at runtime by the web entrypoint. This avoids coupling the feature to the large static `chat.html` and `chat.js` files while keeping the existing settings router unchanged.
