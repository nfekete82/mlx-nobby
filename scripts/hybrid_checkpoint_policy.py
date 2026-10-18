"""Conservative optional secondary exact-cache checkpoint boundaries."""
from __future__ import annotations
import os


def early_checkpoint(checkpoint: int, matched: int, minimum: int) -> int | None:
    """A full cache snapshot can be saved at this earlier prefill boundary.

    Never create a boundary behind already reused tokens or below the APC
    minimum. Defaults off; no cache-manager internals are modified.
    """
    if os.getenv("NOBBY_HYBRID_EARLY_CHECKPOINT") != "1":
        return None
    # The observed third-turn miss diverged 108 tokens before the latest
    # checkpoint. A margin of 160 leaves room without caching only the
    # initial system block.
    candidate = checkpoint - 160
    if candidate < minimum or candidate <= matched:
        return None
    return candidate
