"""Real provider is never launched: diagnostic schema, VAE switch, and safety."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

import image_service as service
import sdxl_worker
spec = importlib.util.spec_from_file_location(
    "diagnose_juggernaut_vae",
    Path(__file__).resolve().parents[1] / "scripts/diagnose-juggernaut-vae.py",
)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def test_schema_limits_diagnostic_to_known_modes():
    service.Generate(prompt="A test portrait", model="juggernaut-xl",
                     sdxl_vae_mode="disabled")
    with pytest.raises(ValidationError):
        service.Generate(prompt="A test portrait", sdxl_vae_mode="none")


def test_resolved_vae_mode_does_not_change_quality_or_sampling(monkeypatch):
    model = {"id":"juggernaut-xl", "model_family":"sdxl","provider":"sdxl",
             "default_steps":30,"default_guidance":5.0}
    monkeypatch.setattr(service, "_generation_model", lambda *_: model)
    params=[]
    for mode in (None, "optimized", "disabled"):
        req=service.Generate(prompt="A realistic human full body portrait",
                             model="juggernaut-xl",width=768,height=1024,
                             steps=30,guidance=5.0,seed=24680,sdxl_vae_mode=mode)
        params.append(service._resolve_generation(req)["params"])
    assert "sdxl_vae_mode" not in params[0]
    assert params[1].pop("sdxl_vae_mode") == "optimized"
    assert params[2].pop("sdxl_vae_mode") == "disabled"
    assert params[0] == params[1] == params[2]


def test_non_sdxl_cannot_disable_vae(monkeypatch):
    monkeypatch.setattr(service, "_generation_model", lambda *_: {
        "id":"FLUX.1-schnell", "model_family":"flux1",
        "provider":"diffusionkit", "default_steps":4, "default_guidance":0,
    })
    req=service.Generate(prompt="A red apple",model="FLUX.1-schnell",
                         sdxl_vae_mode="disabled")
    with pytest.raises(service.HTTPException) as exc:
        service._resolve_generation(req)
    assert exc.value.status_code == 422


def test_vae_can_toggle_both_ways_without_affecting_cpu_offload():
    class Vae:
        use_tiling = False
        use_slicing = False
        def enable_tiling(self): self.use_tiling = True
        def enable_slicing(self): self.use_slicing = True
        def disable_tiling(self): self.use_tiling = False
        def disable_slicing(self): self.use_slicing = False

    offload=Mock()
    p=SimpleNamespace(vae=Vae(), enable_model_cpu_offload=offload)
    sdxl_worker.configure_vae_memory_saving(p)
    assert p.vae.use_tiling and p.vae.use_slicing
    sdxl_worker.configure_vae_memory_saving(p, enabled=False)
    assert not p.vae.use_tiling and not p.vae.use_slicing
    sdxl_worker.configure_vae_memory_saving(p)
    assert p.vae.use_tiling and p.vae.use_slicing
    offload.assert_not_called()


def test_missing_disable_method_cannot_silently_compare_wrong_mode():
    p = SimpleNamespace(vae=SimpleNamespace(use_tiling=True))
    with pytest.raises(RuntimeError, match="disable_tiling"):
        sdxl_worker.configure_vae_memory_saving(p, enabled=False)


def test_script_dry_run_is_safe(capsys, monkeypatch):
    monkeypatch.setattr(diagnostic, "get_json", lambda *_: pytest.fail("network"))
    assert diagnostic.main(["--dry-run", "--seed", "9"]) == 0
    plan=json.loads(capsys.readouterr().out)
    assert plan["seed"] == 9
    assert plan["model"] == "juggernaut-xl"
    assert plan["steps"] == 30
    assert plan["guidance"] == 5.0


def test_script_does_not_start_busy_image_service(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostic, "get_json", lambda *_: {
        "ok":True, "models":["juggernaut-xl"],
        "active_generation":True, "active_job_id":"existing"
    })
    assert diagnostic.main(["--output-dir", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []
