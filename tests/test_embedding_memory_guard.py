import pytest
import embedding_service


def test_embedding_first_load_uses_global_ram_guard(monkeypatch):
    calls = []

    monkeypatch.setattr(
        embedding_service,
        "selected_embedding_model",
        lambda: ("embedding-role", "org/embedding"),
    )
    monkeypatch.setattr(
        embedding_service,
        "_model_entry",
        lambda model_id: {
            "id": model_id,
            "loaded": False,
            "capabilities": ["embeddings"],
            "embedding_dimensions": 3,
        },
    )
    monkeypatch.setattr(
        embedding_service,
        "_has_embedding_capability",
        lambda model: True,
    )
    monkeypatch.setattr(
        embedding_service.runtime_coordinator,
        "ensure_model_load_allowed",
        lambda workload: calls.append(workload),
    )
    monkeypatch.setattr(
        embedding_service,
        "_mlxserve_json",
        lambda path, payload=None, timeout=None: {
            "data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]
        },
    )
    monkeypatch.setattr(
        embedding_service,
        "_embedding_dimensions",
        lambda model_id, model=None: 3,
    )

    result = embedding_service._make_embeddings_sync(["hello"])

    assert calls == ["embedding"]
    assert result["vectors"] == [[1.0, 0.0, 0.0]]


def test_embedding_resident_model_does_not_reapply_load_guard(monkeypatch):
    calls = []

    monkeypatch.setattr(
        embedding_service,
        "selected_embedding_model",
        lambda: ("embedding-role", "org/embedding"),
    )
    monkeypatch.setattr(
        embedding_service,
        "_model_entry",
        lambda model_id: {
            "id": model_id,
            "loaded": True,
            "capabilities": ["embeddings"],
            "embedding_dimensions": 3,
        },
    )
    monkeypatch.setattr(
        embedding_service,
        "_has_embedding_capability",
        lambda model: True,
    )
    monkeypatch.setattr(
        embedding_service.runtime_coordinator,
        "ensure_model_load_allowed",
        lambda workload: calls.append(workload),
    )
    monkeypatch.setattr(
        embedding_service,
        "_mlxserve_json",
        lambda path, payload=None, timeout=None: {
            "data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]
        },
    )
    monkeypatch.setattr(
        embedding_service,
        "_embedding_dimensions",
        lambda model_id, model=None: 3,
    )

    embedding_service._make_embeddings_sync(["hello"], require_loaded=True)

    assert calls == []


def test_foreground_recall_rejects_cold_embedding_without_load_or_inference(monkeypatch):
    monkeypatch.setattr(embedding_service,'selected_embedding_model',lambda:('embedding-role','org/embedding'))
    monkeypatch.setattr(embedding_service,'_model_entry',lambda _: {'loaded':False,'capabilities':['embeddings']})
    monkeypatch.setattr(embedding_service,'_has_embedding_capability',lambda _:True)
    monkeypatch.setattr(embedding_service.runtime_coordinator,'ensure_model_load_allowed',lambda _:pytest.fail('must not load'))
    monkeypatch.setattr(embedding_service,'_mlxserve_json',lambda *a,**kw:pytest.fail('must not infer'))
    with pytest.raises(RuntimeError,match='already loaded'):
        embedding_service._make_embeddings_sync(['fictional query'],require_loaded=True)
