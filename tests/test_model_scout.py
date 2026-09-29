from agent.model_scout_routes import (
    estimate_memory_gb,
    infer_parameter_billions,
    infer_quantization_bits,
    infer_role,
    normalize_candidate,
)
from backend.model_scout_routes import (
    MODEL_SCOUT_SCRIPT,
    inject_model_scout_script,
)


def test_model_scout_infers_common_mlx_model_metadata():
    model_id = "mlx-community/Qwen3.8-27B-Instruct-4bit"
    assert infer_parameter_billions(model_id) == 27.0
    assert infer_quantization_bits(model_id) == 4.0
    assert infer_role(model_id) == "chat"
    assert estimate_memory_gb(27.0, 4.0) == 18.4


def test_model_scout_detects_coding_and_vision_roles():
    assert infer_role("mlx-community/Devstral-Small-24B-4bit") == "coding"
    assert infer_role("mlx-community/Qwen-VL-32B-4bit", ["vision"]) == "vision"


def test_model_scout_normalizes_candidate_and_marks_installed():
    raw = {
        "id": "mlx-community/Qwen3.8-27B-Instruct-4bit",
        "lastModified": "2026-09-28T10:00:00.000Z",
        "downloads": 12000,
        "likes": 220,
        "tags": ["license:apache-2.0", "text-generation"],
        "pipeline_tag": "text-generation",
    }
    candidate = normalize_candidate(
        raw,
        {"memory_gb": 48.0},
        {"mlx-community/qwen3.8-27b-instruct-4bit"},
    )

    assert candidate is not None
    assert candidate["installed"] is True
    assert candidate["status"] == "installed"
    assert candidate["memory_fit"] == "excellent"
    assert candidate["license"] == "apache-2.0"
    assert candidate["suggested_alias"] == "Qwen3.8-27B-Instruct-4bit"


def test_model_scout_marks_oversized_candidate_risky():
    raw = {
        "id": "mlx-community/Huge-120B-Instruct-8bit",
        "tags": [],
        "downloads": 0,
        "likes": 0,
    }
    candidate = normalize_candidate(raw, {"memory_gb": 48.0}, set())

    assert candidate is not None
    assert candidate["memory_fit"] == "risky"
    assert candidate["status"] == "not_recommended"


def test_model_scout_script_injection_is_idempotent():
    marker = b'<script src="/assets/chat.js?v=20260926-shorts-progress"></script>'
    body = b"<html><body>" + marker + b"</body></html>"

    injected = inject_model_scout_script(body)
    assert MODEL_SCOUT_SCRIPT in injected
    assert injected.count(MODEL_SCOUT_SCRIPT) == 1
    assert inject_model_scout_script(injected) == injected
