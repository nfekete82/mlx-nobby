"""Regenerating a Qwen edit must reuse the original image and mask, not the output."""
import copy
import time
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import image_service as service


@pytest.fixture
def edit_runtime(tmp_path, monkeypatch):
    output = tmp_path / "images"
    output.mkdir()
    monkeypatch.setattr(service, "OUTPUT", output)
    monkeypatch.setattr(service.runtime_coordinator, "image_runtime",
                        lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service.runtime_coordinator, "ensure_model_load_allowed",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "sdxl_worker_running", lambda: False)
    model = {
        "id": "mflux-osaurus-qwen-image-2.1-edit",
        "provider": "mflux",
        "model_family": "qwen-image21-edit",
        "capabilities": ["image_edit"],
        "default_steps": 20,
        "default_guidance": 1.0,
        "quantization": "q4",
        "loras": [],
    }
    monkeypatch.setattr(service, "_edit_model", lambda *_args, **_kwargs: model)
    source = output / "1781634000-abc123abc123.png"
    Image.new("RGB", (256, 256), "#444444").save(source)
    mask = output / "painted-mask.png"
    painted = Image.new("L", (256, 256), 0)
    ImageDraw.Draw(painted).rectangle((90, 90, 165, 165), fill=255)
    painted.save(mask)

    calls = []
    def provider(_model, params, target, **_kwargs):
        capture = {
            "prompt": params["prompt"],
            "source_path": params["source_path"],
            "mask_path": params["mask_path"],
            "seed": params["seed"],
            "steps": params["steps"],
            "guidance": params["guidance"],
            "region_low_ram": params.get("_region_low_ram"),
        }
        with Image.open(params["source_path"]) as src:
            capture["crop_size"] = src.size
        with Image.open(params["mask_path"]) as selected:
            capture["mask_nonempty"] = bool(selected.convert("L").getbbox())
        calls.append(capture)
        Image.new("RGB", (params["width"], params["height"]), "#887766").save(target)
    monkeypatch.setattr(service, "run_provider", provider)
    service._jobs.clear()
    client = TestClient(service.app, base_url="http://localhost")
    yield client, source, mask, calls
    for job in list(service._jobs.values()):
        thread = job.get("_thread")
        if thread is not None and thread.ident is not None:
            thread.join(timeout=5)
    service._jobs.clear()


def wait_for(client, job_id):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = client.get("/jobs/" + job_id).json()
        if result.get("status") in {"completed", "failed", "cancelled"}:
            return result
        time.sleep(0.01)
    pytest.fail("edit reroll job timed out")


def start_edit(client, source, mask):
    response = client.post("/jobs", json={
        "operation": "edit",
        "payload": {
            "prompt": "Recolor just the marked portion of the picture",
            "source_path": str(source),
            "mask_path": str(mask),
            "region_edit": True,
            "region_feather_px": 5,
            "model": "auto",
            "quality": "standard",
            "steps": 24,
            "guidance": 3.5,
            "seed": 42,
        },
        "chat_id": "qwen-reroll-test",
        "chat_revision": 0,
    })
    assert response.status_code == 202, response.text
    job = wait_for(client, response.json()["id"])
    assert job["status"] == "completed", job.get("error")
    return job


@pytest.mark.parametrize("variant_count", [2, 4])
def test_qwen_masked_edit_reroll_keeps_source_and_settings(edit_runtime, variant_count):
    client, source, mask, calls = edit_runtime
    original_source, original_mask = source.read_bytes(), mask.read_bytes()
    base = start_edit(client, source, mask)
    assert base["variants_available"] is True
    assert base["result"]["semantic_operation"] == "edit"
    assert service._jobs[base["id"]]["_canonical"]["request"]["source_path"] == str(source)
    assert service._jobs[base["id"]]["_canonical"]["request"]["mask_path"] == str(mask)
    frozen = copy.deepcopy(service._jobs[base["id"]]["_canonical"])
    first_png = (service.OUTPUT / (base["result"]["id"] + ".png")).read_bytes()

    wrong_chat = client.post("/jobs/variants", json={
        "base_job_id": base["id"], "count": variant_count, "include_base": True,
        "chat_id": "other-user", "chat_revision": 0,
    })
    assert wrong_chat.status_code == 404
    wrong_revision = client.post("/jobs/variants", json={
        "base_job_id": base["id"], "count": variant_count, "include_base": True,
        "chat_id": "qwen-reroll-test", "chat_revision": 1,
    })
    assert wrong_revision.status_code == 404

    response = client.post("/jobs/variants", json={
        "base_job_id": base["id"], "count": variant_count, "include_base": True,
        "chat_id": "qwen-reroll-test", "chat_revision": 0,
    })
    assert response.status_code == 202, response.text
    group = response.json()
    assert group["variant_count"] == variant_count
    assert len(group["jobs"]) == variant_count - 1
    for slot in group["jobs"]:
        result = wait_for(client, slot["id"])
        assert result["status"] == "completed", result.get("error")
        assert result["result"]["source_image_id"] == "1781634000-abc123abc123"
        assert result["result"]["source_path"] == str(source)
        assert result["result"]["seed"] != base["result"]["seed"]

    assert source.read_bytes() == original_source
    assert mask.read_bytes() == original_mask
    assert (service.OUTPUT / (base["result"]["id"] + ".png")).read_bytes() == first_png
    assert service._jobs[base["id"]]["_canonical"] == frozen
    assert len(calls) == variant_count
    assert all(item["prompt"] == calls[0]["prompt"] for item in calls)
    assert all(item["steps"] == 24 and item["guidance"] == 3.5 for item in calls)
    assert all(item["region_low_ram"] is True and item["mask_nonempty"] for item in calls)
    assert all(item["crop_size"] == calls[0]["crop_size"] for item in calls)
    assert len({item["seed"] for item in calls}) == variant_count
    # The working crop and mask are regenerated for every job and never reused.
    assert len({item["source_path"] for item in calls}) == variant_count
    assert len({item["mask_path"] for item in calls}) == variant_count


def test_legacy_edit_without_frozen_replay_is_not_recreated(edit_runtime):
    client, source, mask, _ = edit_runtime
    base = start_edit(client, source, mask)
    service._jobs[base["id"]].pop("_canonical")
    response = client.post("/jobs/variants", json={
        "base_job_id": base["id"], "count": 2, "include_base": True,
        "chat_id": "qwen-reroll-test", "chat_revision": 0,
    })
    assert response.status_code == 409
