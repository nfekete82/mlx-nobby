"""Version-compatible LTX image anchors without importing MLX at module import time.

0.16.3 used ImageConditioningInput(path=..., frame_idx=..., strength=...).
0.18.0 moved the immutable dataclass to utils.types, re-exported it from
utils.args, and requires .at()/.guide()/.replace() factory methods.
"""
from __future__ import annotations


def image_conditioning_inputs(anchors, image_cls):
    """Build positional pixel-frame anchors while preserving 'auto' semantics.

    Input frame_index is 0-based. On v0.18, .at() replaces the first frame,
    and guides subsequent frames. Older v0.16.3 receives its original ctor.
    """
    result = []
    for anchor in anchors:
        path = str(anchor["path"])
        frame_idx = int(anchor["frame_index"])
        strength = float(anchor["strength"])
        if hasattr(image_cls, "at"):
            result.append(image_cls.at(path, frame_idx, strength))
        else:
            result.append(image_cls(path=path, frame_idx=frame_idx, strength=strength))
    return result
