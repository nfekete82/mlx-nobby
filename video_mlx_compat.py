"""Version-compatible LTX image anchors without importing MLX at module import time.

0.16.3 used ImageConditioningInput(path=..., frame_idx=..., strength=...).
0.18.0 moved the immutable dataclass to utils.types, re-exported it from
utils.args, and requires .at()/.guide()/.replace() factory methods.
"""
from __future__ import annotations


def initial_image_inputs(image, anchors, crf, image_cls):
    """Opt-in native 0.18 CRF=0 still; preserve the default shorthand exactly.

    Both native distilled stages receive the same explicit replacement at frame
    zero. This changes image preprocessing only, with no extra temporal anchor.
    """
    if crf is None:
        return image, image_conditioning_inputs(anchors, image_cls) if anchors else []
    if type(crf) is not int or crf != 0 or not image or anchors:
        raise ValueError("Experimental image CRF requires a single initial image and CRF 0")
    if not hasattr(image_cls, "replace"):
        raise ValueError("Explicit image CRF requires LTX-MLX v0.18")
    return None, [image_cls.replace(str(image), 0, 1.0, crf=crf)]


def image_conditioning_inputs(anchors, image_cls):
    """Build positional pixel-frame anchors while preserving 'auto' semantics.

    Input frame_index is 0-based. In v0.18, explicit replace/guide bindings
    avoid accidentally replacing the original image at frame 0. The legacy
    v0.16.3 constructor cannot represent an explicit guide at frame 0.
    """
    result = []
    for anchor in anchors:
        path = str(anchor["path"])
        frame_idx = int(anchor["frame_index"])
        strength = float(anchor["strength"])
        binding = str(anchor.get("binding") or "auto").lower()
        if binding not in {"auto", "replace", "guide"}:
            raise ValueError("Unsupported image conditioning binding")
        if binding == "guide":
            if not hasattr(image_cls, "guide"):
                raise ValueError("Explicit image guide requires LTX-MLX v0.18")
            result.append(image_cls.guide(path, frame_idx, strength))
        elif binding == "replace":
            if not hasattr(image_cls, "replace"):
                raise ValueError("Explicit image replace requires LTX-MLX v0.18")
            result.append(image_cls.replace(path, frame_idx, strength))
        elif hasattr(image_cls, "at"):
            result.append(image_cls.at(path, frame_idx, strength))
        else:
            result.append(image_cls(path=path, frame_idx=frame_idx, strength=strength))
    return result
