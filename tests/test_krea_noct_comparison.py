"""Noct evaluation artifacts and existing model contracts; no model imports/GPU."""
import csv
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import image_registry as registry
import image_service as service


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_noct", ROOT / "scripts/prepare-krea-noct-comparison.py")
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


@pytest.fixture
def manifest():
    return json.loads(comparison.MANIFEST.read_text())


def test_all_pairs_have_exactly_matched_prompt_seed_and_resolution(manifest):
    runs = comparison.build_plan(manifest)["runs"]
    assert len(runs) == 30
    for left, right in zip(runs[::2], runs[1::2]):
        for field in ("case_id", "prompt", "negative_prompt", "seed", "width", "height"):
            assert left[field] == right[field]
        assert (left["width"], left["height"]) == (832, 1216)
        assert left["settings"]["steps"] == 35
        assert left["settings"]["guidance"] == 4
        assert right["settings"]["steps"] == 8
        assert right["settings"]["guidance"] == 1
        assert right["status"] == "blocked"
        assert right["request"] is None


def test_prepared_requests_match_actual_native_juggernaut_contract(manifest):
    model = next(item for item in registry.builtin_models() if item["id"] == registry.JUGGERNAUT_XL_ID)
    model["enabled"] = True
    with mock.patch.object(registry, "get_model", return_value=model):
        for run in comparison.build_plan(manifest)["runs"]:
            if run["request"] is None:
                continue
            job = service.ImageJobCreate.model_validate(run["request"])
            assert job.operation == "generate"
            params = service._resolve_generation(service.Generate.model_validate(job.payload))["params"]
            assert params["model"] == "juggernaut-xl"
            assert params["prompt"] == run["prompt"]
            assert params["seed"] == run["seed"]
            assert (params["width"], params["height"]) == (832, 1216)
            assert params["steps"] == 35 and params["guidance"] == 4
            assert params["scheduler"] == "dpmpp-2m-sde-karras"


def test_bundle_contains_only_valid_juggernaut_requests_and_empty_scores(manifest, tmp_path):
    output = tmp_path / "comparison"
    comparison.write_bundle(output, manifest, [42])
    files = sorted((output / "requests").glob("*.json"))
    assert len(files) == 5
    assert all(json.loads(path.read_text())["payload"]["model"] == "juggernaut-xl" for path in files)
    with (output / "scorecard.csv").open() as stream:
        scores = list(csv.DictReader(stream))
    assert len(scores) == 10
    for row in scores:
        assert all(row[field] == "" for field in manifest["rating_dimensions"] + manifest["measurement_fields"])
    with pytest.raises(FileExistsError):
        comparison.write_bundle(output, manifest)
    assert len(list((output / "requests").glob("*.json"))) == 5


@pytest.mark.parametrize("seeds", [[], [42, 42], [-1], [2**32]])
def test_bad_seeds_create_no_output(manifest, tmp_path, seeds):
    with pytest.raises(ValueError):
        comparison.write_bundle(tmp_path / "invalid", manifest, seeds)
    assert not (tmp_path / "invalid").exists()


def test_cannot_silently_enable_unvalidated_candidate(manifest, tmp_path):
    manifest["noct"]["registered_model_id"] = "krea-noct-v4"
    with pytest.raises(ValueError, match="Freigabe"):
        comparison.write_bundle(tmp_path / "unvalidated", manifest)
    assert not (tmp_path / "unvalidated").exists()


@pytest.mark.parametrize("provider", ["mflux", "sdxl"])
def test_no_pseudo_native_krea2_registration(provider):
    with pytest.raises(ValidationError):
        registry.ImageModel(id="krea-noct-v4", name="Krea Noct (experimentell)", provider=provider,
                            repository="Noctaluna/Krea2-Noct-Uncensored", model_family="krea2", base_model="krea-2")
    assert "krea2" not in registry.FAMILIES
    assert not any("noct" in item["id"].lower() for item in registry.builtin_models())


def test_api_model_list_and_unknown_candidate_preserve_existing_models():
    data = registry.initial_registry()
    before = json.dumps(data, sort_keys=True)
    with mock.patch.object(registry, "load_registry", return_value=data), \
         mock.patch.object(service, "describe", side_effect=lambda model: model):
        client = TestClient(service.app, base_url="http://127.0.0.1")
        response = client.get("/models")
        assert response.status_code == 200
        models = {item["id"]: item for item in response.json()["models"]}
        for model_id in [registry.JUGGERNAUT_XL_ID, registry.OSAURUS_QWEN21_EDIT_ID, registry.QWEN_IMAGE_EDIT_ID]:
            assert models[model_id] == next(item for item in data["models"] if item["id"] == model_id)
        assert client.get("/models/krea-noct-v4").status_code == 404
        with pytest.raises(HTTPException) as error:
            service._resolve_generation(service.Generate(prompt="A red ball", model="krea-noct-v4"))
        assert error.value.status_code == 404
    assert json.dumps(data, sort_keys=True) == before


def test_evidence_distinguishes_header_inspection_from_a_real_render():
    evidence = json.loads((ROOT / "docs/krea-noct-compatibility-2026-10-29.json").read_text())
    assert evidence["revision"] == "d93fbcb45e6f6995f2ecdd4edfdb1ef12db6e6e4"
    assert evidence["dtype_counts"]["I8"] == 224
    assert evidence["bytes_read"] == 88360 < evidence["file_bytes"]
    assert evidence["gpu_load_result"] == "not attempted"
    assert evidence["render_seconds"] is None
