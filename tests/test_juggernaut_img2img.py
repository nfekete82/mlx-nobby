"""Juggernaut Ragnarok img2img safety, edit routing and deterministic worker tests."""
import io
import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image
from pydantic import ValidationError

import image_registry as registry
import image_service as service
import sdxl_worker
from image_img2img import prepare_sdxl_img2img_source


def test_juggernaut_is_an_explicit_img2img_edit_candidate():
    juggernaut = next(model for model in registry.builtin_models()
                     if model["id"] == "juggernaut-xl")
    assert juggernaut["provider"] == "sdxl"
    assert {"image_edit", "img2img", "edit_strength"} <= set(juggernaut["capabilities"])


def test_sdxl_source_copy_is_bounded_rgb_private_and_original_unmodified(tmp_path):
    source = tmp_path / "original.png"
    target = tmp_path / "working.png"
    Image.new("RGBA", (2400, 1600), (100, 60, 30, 120)).save(source)
    before = source.read_bytes()
    assert prepare_sdxl_img2img_source(source, target) == (1024, 680)
    with Image.open(target) as working:
        assert working.size == (1024, 680)
        assert working.mode == "RGB"
    assert target.stat().st_mode & 0o777 == 0o600
    assert source.read_bytes() == before


def test_sdxl_source_rejects_extreme_panorama_before_creating_file(tmp_path):
    src, dest = tmp_path / "wide.png", tmp_path / "work.png"
    Image.new("RGB", (2000, 200)).save(src)
    with pytest.raises(ValueError, match="4:1"):
        prepare_sdxl_img2img_source(src, dest)
    assert not dest.exists()


def test_edit_schema_rejects_invalid_strength():
    for strength in (0, -0.1, 1.1, "nan"):
        with pytest.raises(ValidationError):
            service.Edit(prompt="A different portrait", source_path="/tmp/a.png",
                         model="juggernaut-xl", strength=strength)


def test_sdxl_edit_preserves_source_and_uses_default_or_explicit_strength(tmp_path, monkeypatch):
    juggernaut = next(model for model in registry.builtin_models()
                     if model["id"] == "juggernaut-xl")
    source = tmp_path / "original.png"
    Image.new("RGB", (640, 448), "navy").save(source)
    original = source.read_bytes()
    monkeypatch.setattr(service, "OUTPUT", tmp_path / "outputs")
    monkeypatch.setattr(service, "_edit_model", lambda *_args, **_kw: juggernaut)
    monkeypatch.setattr(service.runtime_coordinator,
                        "ensure_model_load_allowed", lambda *_: None)
    monkeypatch.setattr(service, "image_change_advisory", lambda *_: None)
    monkeypatch.setattr(service, "comparison_image_id", lambda *_: None)
    seen = []

    def fake_provider(model, params, output, **_kwargs):
        assert model["id"] == "juggernaut-xl"
        assert params["source_path"] != str(source)
        assert Path(params["source_path"]).is_file()
        seen.append({key: params[key] for key in
                     ("width", "height", "source_path", "strength", "steps", "guidance")})
        with Image.open(params["source_path"]) as image:
            image.save(output)

    monkeypatch.setattr(service, "run_provider", fake_provider)
    for desired in (None, 0.75):
        request = service.Edit(prompt="Make a warm cinematic portrait",
                               source_path=str(source), model="juggernaut-xl",
                               strength=desired, steps=25, guidance=5.0)
        result = service._edit_result(request)
        assert result["model"] == "juggernaut-xl"
        assert result["strength"] == (0.45 if desired is None else desired)
        assert Path(result["path"]).exists()
        assert result["source_path"] == str(source)
    assert source.read_bytes() == original
    assert all(not Path(item["source_path"]).exists() for item in seen)


def test_sdxl_edit_rejects_qwen_masks_and_multiple_sources(tmp_path, monkeypatch):
    juggernaut = next(model for model in registry.builtin_models()
                     if model["id"] == "juggernaut-xl")
    path = tmp_path / "original.png"
    Image.new("RGB", (512, 512)).save(path)
    monkeypatch.setattr(service, "_edit_model", lambda *_args, **_kw: juggernaut)
    with pytest.raises(Exception, match="keine Maske"):
        service._edit_result(service.Edit(prompt="Make it brighter",
            source_path=str(path), model="juggernaut-xl", mask_path=str(path)))
    with pytest.raises(Exception, match="genau ein Bild"):
        service._edit_result(service.Edit(prompt="Make it brighter",
            source_paths=[str(path), str(path)], model="juggernaut-xl"))


def test_sdxl_worker_uses_existing_weights_for_img2img_and_keeps_text_generation(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (512, 512), "red").save(source)
    events = []
    shared = object()

    class Vae:
        def enable_tiling(self): pass
        def enable_slicing(self): pass

    class Scheduler:
        def __init__(self): self.config = {}
        @classmethod
        def from_config(cls, *_args, **_kw): return cls()

    class FakeText:
        def __init__(self):
            self.scheduler = Scheduler()
            self.vae = Vae()
            self.components = {"shared": shared, "vae": self.vae}
        @classmethod
        def from_single_file(cls, *_a, **_kw):
            events.append("weights-loaded")
            return cls()
        def enable_model_cpu_offload(self, **kw):
            assert kw["device"] == "mps"
            events.append("offloaded")
        def __call__(self, **kw):
            assert "image" not in kw
            events.append("text")
            return types.SimpleNamespace(images=[Image.new("RGB", (512, 512))])

    class FakeImg:
        def __init__(self, shared, vae):
            assert shared is globals_shared
            self.vae = vae
            self.scheduler = None
            events.append("img-wrapper-created")
        def __call__(self, **kw):
            assert kw["strength"] == 0.45
            assert kw["image"].size == (512, 512)
            assert kw["num_inference_steps"] == 20
            events.append("img2img")
            kw["callback_on_step_end"](self, 0, 0, {})
            return types.SimpleNamespace(images=[Image.new("RGB", (512, 512))])

    globals_shared = shared
    fake_torch = types.ModuleType("torch")
    fake_torch.float16 = "float16"
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: True))
    fake_torch.mps = types.SimpleNamespace(empty_cache=lambda: None)
    fake_torch.Generator = lambda **kw: types.SimpleNamespace(manual_seed=lambda *_: object())
    fake_diffusers = types.ModuleType("diffusers")
    fake_diffusers.StableDiffusionXLPipeline = FakeText
    fake_diffusers.StableDiffusionXLImg2ImgPipeline = FakeImg
    fake_diffusers.DPMSolverMultistepScheduler = Scheduler
    req = dict(checkpoint=str(tmp_path / "weights.safetensors"),
               config=str(tmp_path / "config"),
               params={"prompt": "A cinematic portrait", "negative_prompt": "",
                       "width": 512, "height": 512, "steps": 20,
                       "guidance": 5.0, "seed": 1})
    inputs = [
        {**req, "request_id": "text", "output": str(tmp_path / "text.png")},
        {**req, "request_id": "img", "output": str(tmp_path / "img.png"),
         "params": {**req["params"], "source_path": str(source), "strength": 0.45}},
    ]
    output = io.StringIO()
    with mock.patch.dict(sys.modules, {"torch": fake_torch, "diffusers": fake_diffusers}), \
         mock.patch.object(sdxl_worker.sys, "stdin", io.StringIO("".join(json.dumps(x) + "\n" for x in inputs))), \
         mock.patch.object(sdxl_worker.sys, "stdout", output):
        sdxl_worker.main()
    completed = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in completed] == ["complete", "runtime", "complete"]
    assert completed[1]["total_steps"] == 9
    assert events == ["weights-loaded", "offloaded", "text", "img-wrapper-created", "img2img"]
    assert (tmp_path / "img.png").is_file()
