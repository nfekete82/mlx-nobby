from pathlib import Path


def test_memory_manager_documentation_mentions_local_storage_and_settings():
    text = (Path(__file__).parents[1] / "docs" / "MEMORY_MANAGER.md").read_text()
    assert "Settings → Memory" in text
    assert "~/.config/mlx-web/memory.db" in text
    assert "/api/mlx/memory" in text
