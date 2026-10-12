"""Guard against destructive edits of existing SearXNG local settings."""
from pathlib import Path

import pytest

from scripts.configure_searxng_engines import (
    configure, proposed_settings, reconciled_settings,
    LEGACY_OVERRIDES, GENERATED_MARKER,
)


def test_appends_only_engine_overrides_and_preserves_secret_lines():
    original = ("use_default_settings: true\nserver:\n  secret_key: 'keep-me'\n"
                "search:\n  formats:\n    - html\n    - json\n")
    updated = proposed_settings(original)
    assert updated.startswith(original)
    assert "secret_key: 'keep-me'" in updated
    for name in ("brave", "duckduckgo", "google cse", "startpage", "qwant", "yahoo"):
        assert f"  - name: {name}\n    disabled: true" in updated
    for name in ("bing", "google", "bpb"):
        assert f"  - name: {name}\n    disabled: false" in updated


def test_dry_run_does_not_modify_local_settings_or_create_backup(tmp_path):
    path = tmp_path / "settings.yml"
    path.write_text("use_default_settings: true\nserver:\n  secret_key: priv\n")
    assert configure(path, apply=False)["applied"] is False
    assert path.read_text() == "use_default_settings: true\nserver:\n  secret_key: priv\n"
    assert len(list(tmp_path.iterdir())) == 1


def test_apply_preserves_private_backup_and_blocks_second_apply(tmp_path):
    path = tmp_path / "settings.yml"
    original = "use_default_settings: true\nserver:\n  secret_key: priv\n"
    path.write_text(original)
    path.chmod(0o600)
    outcome = configure(path, apply=True)
    backup = Path(outcome["backup"])
    assert outcome["applied"]
    assert backup.read_text() == original
    assert path.read_text().startswith(original)
    assert (path.stat().st_mode & 0o777) == 0o600
    assert (backup.stat().st_mode & 0o777) == 0o600
    with pytest.raises(ValueError, match="engines"):
        configure(path, apply=True)


def test_refuses_existing_engine_section(tmp_path):
    path = tmp_path / "settings.yml"
    original = "use_default_settings: true\nengines:\n  - name: google\n    disabled: false\n"
    path.write_text(original)
    with pytest.raises(ValueError, match="engines"):
        configure(path, apply=True)
    assert path.read_text() == original
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("settings", [
    "use_default_settings: false\n",
    "server:\n  secret_key: priv\n",
    "use_default_settings:\n  engines:\n    remove:\n      - bing\n",
])
def test_refuses_custom_default_settings_mode(settings):
    with pytest.raises(ValueError, match="use_default_settings"):
        proposed_settings(settings)


def test_refuses_symlink(tmp_path):
    target = tmp_path / "actual"
    target.write_text("use_default_settings: true\n")
    link = tmp_path / "settings.yml"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="non-symlink"):
        configure(link, apply=True)
    assert target.read_text() == "use_default_settings: true\n"


def test_reconcile_known_generated_block_only(tmp_path):
    original = (
        "use_default_settings: true\nserver:\n  secret_key: priv\n\n"
        + GENERATED_MARKER + "\nengines:\n"
        + "".join(
            f"  - name: {name}\n    disabled: {str(disabled).lower()}\n"
            for name, disabled in LEGACY_OVERRIDES
        )
    )
    updated = reconciled_settings(original)
    assert "secret_key: priv" in updated
    assert "  - name: qwant\n    disabled: true" in updated
    assert "  - name: yahoo\n    disabled: true" in updated
    assert "  - name: google\n    disabled: false" in updated
    assert "  - name: bpb\n    disabled: false" in updated
    assert reconciled_settings(updated) == updated

    path = tmp_path / "settings.yml"
    path.write_text(original)
    outcome = configure(path, apply=True, reconcile=True)
    assert outcome["applied"]
    assert Path(outcome["backup"]).read_text() == original
    assert path.read_text() == updated


def test_reconcile_refuses_custom_engines():
    custom = "use_default_settings: true\nengines:\n  - name: bing\n    disabled: false\n"
    with pytest.raises(ValueError, match="Custom engines"):
        reconciled_settings(custom)
