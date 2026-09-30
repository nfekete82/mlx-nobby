from pathlib import Path

import image_pipeline_v2 as pipeline
import image_registry as registry


ROOT = Path(__file__).resolve().parents[1]


def test_photoreal_people_prefer_juggernaut():
    plan = pipeline.route_plan(
        "Photorealistic portrait of a woman in soft window light",
        "FLUX.1-schnell",
    )
    assert plan["intent"] == "photoreal_person"
    assert plan["candidates"][0] == registry.JUGGERNAUT_XL_ID
    assert registry.MLXSERVE_QWEN_IMAGE21_ID in plan["candidates"]


def test_plain_portrait_prefers_juggernaut_but_illustration_does_not():
    portrait = pipeline.route_plan("Porträt einer Frau", "FLUX.1-schnell")
    assert portrait["intent"] == "photoreal_person"
    assert portrait["candidates"][0] == registry.JUGGERNAUT_XL_ID

    illustration = pipeline.route_plan(
        "watercolor illustration portrait of a woman",
        "FLUX.1-schnell",
    )
    assert illustration["intent"] == "illustration"
    assert illustration["candidates"][0] == registry.MLXSERVE_QWEN_IMAGE21_ID


def test_text_and_fast_routes_use_specialized_models():
    text = pipeline.route_plan(
        "Create a poster with readable typography and a logo",
        "FLUX.1-schnell",
    )
    assert text["intent"] == "text_layout"
    assert text["candidates"][0] == registry.MLXSERVE_QWEN_IMAGE21_ID

    fast = pipeline.route_plan(
        "quick preview draft image of a city",
        "FLUX.1-schnell",
    )
    assert fast["intent"] == "fast_draft"
    assert fast["candidates"][0] == registry.Z_IMAGE_TURBO_ID


def test_generic_route_respects_default_and_never_retains_prompt():
    secret_prompt = "blue geometric shapes with private-marker-123"
    plan = pipeline.route_plan(secret_prompt, "FLUX.1-schnell")
    assert plan["intent"] == "generic"
    assert plan["candidates"][0] == "FLUX.1-schnell"
    assert secret_prompt not in repr(plan)
    assert "prompt" not in plan


def test_pipeline_v2_is_wired_into_production_layers():
    worker = (ROOT / "sdxl_worker.py").read_text(encoding="utf-8")
    service = (ROOT / "image_service_pipeline.py").read_text(encoding="utf-8")
    launchd = (
        ROOT / "launchd/templates/de.nobby.mlx-images.plist.template"
    ).read_text(encoding="utf-8")
    agent_entrypoint = (ROOT / "agent/entrypoint.py").read_text(encoding="utf-8")
    backend_entrypoint = (ROOT / "backend/entrypoint.py").read_text(encoding="utf-8")

    assert 'request.get("operation") == "prewarm"' in worker
    assert '@app.post("/prewarm")' in service
    assert '@app.get("/pipeline")' in service
    assert "core._generation_model = _route_generation_model" in service
    assert "core._generate_result = _observed_generate_result" in service
    assert "image_service_pipeline:app" in launchd
    assert "install_image_pipeline_routes(app)" in agent_entrypoint
    assert "install_image_pipeline_routes(app, agent_json_request)" in backend_entrypoint
