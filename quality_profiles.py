"""Central model-aware media quality profiles.

Profiles describe only settings supported by the installed runtimes.  Explicit
request parameters are applied by the services after profile resolution.
"""

# Exact /16 canvases for the existing format picker only. No arbitrary large
# canvases; square is the largest pixel budget (2,768,896 pixels).
ULTRA_PLUS_DIMENSIONS = {
    (3, 4): (1248, 1664), (4, 3): (1664, 1248),
    (1, 1): (1664, 1664),
    (16, 9): (1792, 1008), (9, 16): (1008, 1792),
    (13, 19): (1248, 1824),
}


def ultra_plus_dimensions(width, height):
    from math import gcd
    divisor = gcd(width, height)
    try:
        return ULTRA_PLUS_DIMENSIONS[(width // divisor, height // divisor)]
    except KeyError:
        raise ValueError("Ultra+ unterstützt nur 1:1, 3:4, 4:3, 16:9, 9:16 und 13:19") from None


IMAGE_PROFILES = {
    "qwen-image21-edit": {
        "fast": {"steps": 10, "guidance": 1.0, "long_edge": 512},
        "standard": {"steps": 20, "guidance": 1.0, "long_edge": 768},
        "quality": {"steps": 40, "guidance": 1.0, "long_edge": 1024},
    },
    "juggernaut-xl": {
        # Ragnarok: 30-40 steps, CFG 3-6. Lower CFG favors photorealism.
        # Fast remains a deliberate lower-resolution / fewer-step tradeoff.
        "fast": {"steps": 20, "guidance": 4.0, "long_edge": 768},
        "standard": {"steps": 35, "guidance": 4.0, "long_edge": 1216},
        "quality": {"steps": 30, "guidance": 4.0, "long_edge": 1216},
    },
    "cyberrealistic-pony-v18": {
        "fast": {"steps": 20, "guidance": 5.0, "long_edge": 768},
        "standard": {"steps": 35, "guidance": 5.0, "long_edge": 1216},
        "quality": {"steps": 35, "guidance": 5.5, "long_edge": 1216},
    },
    "qwen-image21": {
        "fast": {"steps": 20, "guidance": 0.0, "long_edge": 768},
        "standard": {"steps": 30, "guidance": 0.0, "long_edge": 768},
        "quality": {"steps": 40, "guidance": 0.0, "long_edge": 1024},
    },
    "qwen-image21-mflux": {
        "fast": {"steps": 20, "guidance": 1.0, "long_edge": 768},
        "standard": {"steps": 30, "guidance": 1.0, "long_edge": 1024},
        "quality": {"steps": 40, "guidance": 1.0, "long_edge": 1024},
    },
    "boogu": {
        "fast": {"steps": 4, "guidance": 0.0, "long_edge": 768},
        "standard": {"steps": 8, "guidance": 0.0, "long_edge": 1024},
        "quality": {"steps": 8, "guidance": 0.0, "long_edge": 1024},
    },
    "sdxl": {
        "fast": {"steps": 20, "guidance": 4.5, "long_edge": 768},
        "standard": {"steps": 30, "guidance": 5.0, "long_edge": 1024},
        "quality": {"steps": 35, "guidance": 5.0, "long_edge": 1216},
    },
    "flux1-schnell": {
        "fast": {"steps": 4, "guidance": 0.0, "long_edge": 768},
        "standard": {"steps": 4, "guidance": 0.0, "long_edge": 1024},
        "quality": {"steps": 4, "guidance": 0.0, "long_edge": 1024},
    },
    "flux2-klein-distilled": {
        "fast": {"steps": 4, "guidance": 1.0, "long_edge": 768},
        "standard": {"steps": 4, "guidance": 1.0, "long_edge": 1024},
        "quality": {"steps": 4, "guidance": 1.0, "long_edge": 1024},
    },
    "z-image-turbo": {
        "fast": {"steps": 6, "guidance": 0.0, "long_edge": 768},
        "standard": {"steps": 9, "guidance": 0.0, "long_edge": 1024},
        "quality": {"steps": 9, "guidance": 0.0, "long_edge": 1024},
    },
    "qwen-image-edit": {
        "fast": {"steps": 4, "guidance": 3.5},
        "standard": {"steps": 8, "guidance": 3.5},
        "quality": {"steps": 8, "guidance": 3.5},
    },
    "qwen-image": {
        "fast": {"steps": 20, "guidance": 3.0, "long_edge": 768},
        "standard": {"steps": 30, "guidance": 3.5, "long_edge": 1024},
        "quality": {"steps": 40, "guidance": 4.0, "long_edge": 1024},
    },
    "flux1-dev": {
        "fast": {"steps": 20, "guidance": 3.0, "long_edge": 768},
        "standard": {"steps": 28, "guidance": 3.5, "long_edge": 1024},
        "quality": {"steps": 35, "guidance": 3.5, "long_edge": 1024},
    },
    "z-image": {
        "fast": {"steps": 20, "guidance": 3.0, "long_edge": 768},
        "standard": {"steps": 30, "guidance": 4.0, "long_edge": 1024},
        "quality": {"steps": 40, "guidance": 4.0, "long_edge": 1024},
    },
}

VIDEO_PROFILES = {
    "ltx-2.5": {
        "preview": {
            "resolution": "preview", "steps": 2, "pipeline": "preview-1+1",
            "stage_1_steps": 1, "stage_2_steps": 1,
        },
        "fast": {
            "resolution": "540p", "steps": 11, "pipeline": "distilled-two-stage",
            "stage_1_steps": 8, "stage_2_steps": 3,
        },
        "standard": {
            "resolution": "720p", "steps": 11, "pipeline": "distilled-two-stage",
            "stage_1_steps": 8, "stage_2_steps": 3,
        },
        "quality": {
            "resolution": "1080p", "steps": 11, "pipeline": "distilled-two-stage",
            "stage_1_steps": 8, "stage_2_steps": 3,
        },
    },
}


def image_profile_key(model):
    model_id = str(model.get("id") or "")
    if model_id in {"juggernaut-xl", "cyberrealistic-pony-v18"}:
        return model_id
    if model_id == "mflux-qwen-image-2.1":
        return "qwen-image21-mflux"
    family = str(model.get("model_family") or "")
    base = str(model.get("base_model") or "")
    if family == "flux1":
        return "flux1-schnell" if base == "schnell" else "flux1-dev"
    if family == "flux2-klein" and "base" not in base:
        return "flux2-klein-distilled"
    return family


def resolve_image_profile(model, quality):
    profiles = IMAGE_PROFILES.get(image_profile_key(model))
    if quality == "ultra_plus":
        if model.get("id") != "juggernaut-xl" or model.get("provider") != "sdxl":
            raise ValueError("Ultra+ ist nur für Juggernaut XL / SDXL verfügbar")
        return {"steps": 40, "guidance": 4.0,
                "dimension_policy": "ultra_plus_exact_aspect", "max_pixels": 1664 ** 2}
    if quality == "ultra":
        # Native generation; reuse model-specific Quality guidance and steps.
        base = dict(profiles["quality"]) if profiles and "quality" in profiles else {
            "steps": int(model["default_steps"]),
            "guidance": float(model["default_guidance"]),
        }
        if image_profile_key(model) == "juggernaut-xl":
            # Keep the high-detail Ultra profile independent of faster Quality.
            base["steps"] = 40
        base["long_edge"] = 1536
        return base
    if profiles and quality in profiles:
        return dict(profiles[quality])
    return {
        "steps": int(model["default_steps"]),
        "guidance": float(model["default_guidance"]),
        "long_edge": 1024 if quality == "quality" else 768,
    }


def resolve_video_profile(model, quality):
    family = str(model.get("model_family") or "ltx-2.5")
    return dict(VIDEO_PROFILES[family][quality])


def dimensions_for_long_edge(width, height, long_edge):
    """Preserve the selected aspect ratio and return /16-safe dimensions."""
    if width >= height:
        resolved_width = long_edge
        resolved_height = max(256, round(long_edge * height / width / 16) * 16)
    else:
        resolved_height = long_edge
        resolved_width = max(256, round(long_edge * width / height / 16) * 16)
    return resolved_width, resolved_height
