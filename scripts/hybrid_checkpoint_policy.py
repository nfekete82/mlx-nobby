"""Conservative optional secondary exact-cache checkpoint boundaries."""
from __future__ import annotations
import os


def early_checkpoint(checkpoint: int, matched: int, minimum: int,
                     prefill_step_size: int | None = None) -> int | None:
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

    if os.getenv("NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE") == "1":
        # Preserve *exactly* the pre-existing inference call boundaries.
        # Prefill chunks start at matched (the restored cache offset),
        # advance in fixed steps, and end at the full checkpoint.
        # Use the last natural boundary at or before the early target.
        # Any partial extra step would change the numerical compute path.
        if prefill_step_size is None or int(prefill_step_size) < 1:
            return None
        step = int(prefill_step_size)
        natural_steps = (candidate - matched) // step
        if natural_steps < 1:
            return None
        aligned = matched + natural_steps * step
        if aligned < minimum or aligned >= checkpoint:
            return None
        return aligned

    return candidate
