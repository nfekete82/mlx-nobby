from types import SimpleNamespace

import pytest

from agent import automation_notifications
from agent import automations
from agent.automation_routes import _notification_payload


@pytest.fixture()
def isolated_automations(tmp_path, monkeypatch):
    root = tmp_path / "mlx-web"
    monkeypatch.setattr(automations, "ROOT", root)
    monkeypatch.setattr(automations, "AUTOMATIONS_DB", root / "automations.db")
    return root


def make_run():
    item = automations.create_automation({
        "name": "Scout",
        "kind": "model_scout",
        "schedule": {"type": "manual", "timezone": "UTC"},
    })
    run = automations.create_run(item["id"])
    return item, run


def test_notification_persistence_and_read_state(isolated_automations):
    item, run = make_run()
    note = automation_notifications.create_notification(
        automation_id=item["id"],
        run_id=run["id"],
        level="success",
        title="Model Scout",
        message="2 neue Kandidaten gefunden.",
    )

    assert note["unread"] is True
    assert note["delivered"] is False
    assert automation_notifications.unread_count() == 1
    assert automation_notifications.list_notifications()[0]["id"] == note["id"]

    delivered = automation_notifications.mark_delivery(note["id"], delivered=True)
    assert delivered["delivered"] is True
    assert delivered["delivery_error"] is None

    read = automation_notifications.mark_read(note["id"])
    assert read["unread"] is False
    assert automation_notifications.unread_count() == 0


def test_notification_is_deduplicated_by_run(isolated_automations):
    item, run = make_run()
    first = automation_notifications.create_notification(
        automation_id=item["id"],
        run_id=run["id"],
        level="success",
        title="Scout",
        message="First",
    )
    second = automation_notifications.create_notification(
        automation_id=item["id"],
        run_id=run["id"],
        level="error",
        title="Other",
        message="Second",
    )

    assert second["id"] == first["id"]
    assert second["title"] == "Scout"
    assert len(automation_notifications.list_notifications()) == 1


def test_model_scout_only_notifies_when_candidates_are_new():
    automation = {"name": "Weekly Scout", "kind": "model_scout"}
    result = {
        "kind": "model_scout",
        "count": 2,
        "candidates": [{"id": "mlx/a"}, {"id": "mlx/b"}],
    }

    first = _notification_payload(
        automation,
        status="completed",
        result=result,
        had_previous_scout=False,
    )
    assert first["title"] == "Model Scout"
    assert "Erster Scan" in first["message"]

    unchanged = _notification_payload(
        automation,
        status="completed",
        result=result,
        previous_scout_ids={"mlx/a", "mlx/b"},
        had_previous_scout=True,
    )
    assert unchanged is None

    changed = _notification_payload(
        automation,
        status="completed",
        result={
            **result,
            "count": 3,
            "candidates": [
                {"id": "mlx/a"},
                {"id": "mlx/b"},
                {"id": "mlx/c"},
            ],
        },
        previous_scout_ids={"mlx/a", "mlx/b"},
        had_previous_scout=True,
    )
    assert changed["level"] == "success"
    assert "1 neue MLX-Kandidaten" in changed["message"]
    assert "mlx/c" in changed["message"]


def test_agent_approval_and_failure_notifications():
    automation = {"name": "Projektcheck", "kind": "agent"}

    approval = _notification_payload(automation, status="needs_approval")
    assert approval["level"] == "warning"
    assert approval["title"] == "Freigabe erforderlich"

    failed = _notification_payload(
        automation,
        status="failed",
        error="Test fehlgeschlagen",
    )
    assert failed["level"] == "error"
    assert "Test fehlgeschlagen" in failed["message"]

    completed = _notification_payload(
        automation,
        status="completed",
        result={"answer": "Alles sauber."},
    )
    assert completed["title"] == "Projektcheck"
    assert completed["message"] == "Alles sauber."


def test_native_delivery_passes_content_as_argv(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(automation_notifications.sys, "platform", "darwin")
    monkeypatch.setattr(automation_notifications.shutil, "which", lambda _: "/usr/bin/osascript")
    monkeypatch.setattr(automation_notifications.subprocess, "run", fake_run)

    delivered, error = automation_notifications.deliver_macos(
        'Title "quoted"',
        'Message with "quotes" and shell $syntax',
    )

    assert delivered is True
    assert error is None
    assert captured["args"][-2] == 'Title "quoted"'
    assert captured["args"][-1] == 'Message with "quotes" and shell $syntax'
    assert 'Title "quoted"' not in captured["args"][2]
