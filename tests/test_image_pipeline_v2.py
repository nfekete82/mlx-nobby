from pathlib import Path

import image_pipeline_v2 as pipeline
import image_registry as registry


ROOT = Path(__file__).resolve().parents[1]


def test_auto_candidates_are_only_configured_default_for_every_intent():
    cases = {
        "Photorealistic portrait of a woman in soft window light": "photoreal_person",
        "Porträt einer Frau": "photoreal_person",
        "watercolor illustration portrait of a woman": "illustration",
        "Create a poster with readable typography and a logo": "text_layout",
        "quick preview draft image of a city": "fast_draft",
        "a highly complex prompt with high prompt fidelity": "complex_prompt",
        "blue geometric shapes": "generic",
    }
    for configured in (registry.JUGGERNAUT_XL_ID, registry.MLXSERVE_QWEN_IMAGE21_ID, "FLUX.1-schnell"):
        for prompt, intent in cases.items():
            plan = pipeline.route_plan(prompt, configured)
            assert plan["intent"] == intent
            assert plan["reason"] == "configured-default"
            assert plan["candidates"] == [configured]
    assert pipeline.route_plan("photo", None)["candidates"] == []


def test_routes_do_not_retaina_prompt():
    secret_prompt = "blue geometric shapes with private-marker-123"
    plan = pipeline.route_plan(secret_prompt, "FLUX.1-schnell")
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
