"""CPU-only regression tests for a non-disruptive LTX-MLX 0.18 rollout."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from video_mlx_compat import image_conditioning_inputs
from video_multi_image import keyframe_capabilities


ANCHORS = [
    {"path": "/tmp/start.png", "frame_index": 0, "strength": 1.0},
    {"path": "/tmp/end.png", "frame_index": 120, "strength": 0.8},
]


@dataclass
class LegacyImage:
    path: str
    frame_idx: int
    strength: float


@dataclass
class Image018:
    path: str
    frame_idx: int
    strength: float
    binding: str

    @classmethod
    def at(cls, path, frame_idx, strength, crf=None):
        return cls(path, frame_idx, strength,
                   "replace" if frame_idx == 0 else "guide")


@pytest.mark.parametrize("factory", [LegacyImage, Image018])
def test_image_anchor_conversion_matches_legacy_and_018(factory):
    result = image_conditioning_inputs(ANCHORS, factory)
    assert len(result) == 2
    assert [r.frame_idx for r in result] == [0, 120]
    assert [r.strength for r in result] == [1.0, 0.8]
    assert [r.path for r in result] == ["/tmp/start.png", "/tmp/end.png"]
    if factory is Image018:
        assert [r.binding for r in result] == ["replace", "guide"]


def test_image_anchor_factory_propagates_invalid_payload():
    with pytest.raises((KeyError, ValueError, TypeError)):
        image_conditioning_inputs([{"path": "a", "frame_index": "bad", "strength": 1}], Image018)


def _make_package(root, *, version):
    package = root / "packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx"
    (package / "utils").mkdir(parents=True)
    (package / "distilled.py").write_text("def generate_two_stage(self, *, images=None): pass")
    (package / "ti2vid_two_stages.py").write_text("def generate_and_save(self, *, images=None): pass")
    if version == "018":
        (package / "utils/args.py").write_text(
            "from ltx_pipelines_mlx.utils.types import ImageConditioningInput"
        )
        (package / "utils/types.py").write_text(
            "class ImageConditioningInput:\n"
            "    @classmethod\n"
            "    def at(cls, path, frame_idx, strength, crf=None): pass\n"
        )
    else:
        (package / "utils/args.py").write_text("class ImageConditioningInput: pass")
    return package


@pytest.mark.parametrize("version", ["016", "018"])
def test_native_keyframes_detected_in_both_upstream_layouts(tmp_path, version):
    _make_package(tmp_path, version=version)
    assert keyframe_capabilities(tmp_path)["native_keyframes"] is True


def test_native_keyframe_probe_fails_closed_if_018_factory_missing(tmp_path):
    package = _make_package(tmp_path, version="018")
    (package / "utils/types.py").write_text("class ImageConditioningInput: pass")
    assert keyframe_capabilities(tmp_path)["native_keyframes"] is False


def test_staged_setup_uses_exact_tag_commit_existing_weights_and_separate_root():
    script = Path("scripts/stage-ltx-video-mlx-018").read_text()
    assert 'UPSTREAM_VERSION="0.18.0"' in script
    assert 'UPSTREAM_COMMIT="b82b97e3d000e01361f8cfcb745244b15b89a521"' in script
    assert "ltx-2-mlx-v0.18.0" in script
    assert '[[ "$RUNTIME_ROOT" != "$LEGACY_ROOT" ]]' in script
    assert "MODEL_DIR" in script and ".mlx-nobby-ready" in script
    assert "snapshot_download" not in script
    assert "hf download" not in script
    assert "uv sync --frozen" in script
    assert "generate --help" in script and "retake --help" in script


def test_stable_runtime_setup_and_launchagent_remain_unchanged():
    setup = Path("scripts/setup-ltx-video-mlx").read_text()
    template = Path("launchd/templates/de.nobby.mlx-video.plist.template").read_text()
    assert 'UPSTREAM_VERSION="0.16.3"' in setup
    assert "ae3b7ea9583db775bd4a1dfb506fb789585021e7" in setup
    assert "ltx-2-mlx</string>" in template
    assert "ltx-2-mlx-v0.18.0</string>" not in template


def test_opt_in_switch_requires_idle_service_and_explicit_apply():
    switch = Path("scripts/switch-ltx-video-runtime").read_text()
    assert 'parser.add_argument("--apply", action="store_true"' in switch
    assert "idle_service()" in switch
    assert "check_checkout(target_root, args.to)" in switch
    assert "shutil.copy2(plist, backup)" in switch
    assert 'service_command("bootstrap", plist)' in switch
