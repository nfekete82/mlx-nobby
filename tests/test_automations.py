from datetime import datetime, timezone

import pytest

from agent import automations


@pytest.fixture()
def isolated_automations(tmp_path, monkeypatch):
    root = tmp_path / "mlx-web"
    monkeypatch.setattr(automations, "ROOT", root)
    monkeypatch.setattr(automations, "AUTOMATIONS_DB", root / "automations.db")
    return root


def ts(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()


def test_manual_agent_automation_crud(isolated_automations):
    item = automations.create_automation({
        "name": "Daily status",
        "kind": "agent",
        "prompt": "Check the project status.",
        "mode": "diagnostic",
        "schedule": {"type": "manual", "timezone": "UTC"},
    })

    assert item["name"] == "Daily status"
    assert item["kind"] == "agent"
    assert item["next_run_at"] is None
    assert item["enabled"] is True
    assert automations.get_automation(item["id"])["prompt"] == "Check the project status."

    updated = automations.update_automation(item["id"], {"enabled": False})
    assert updated["enabled"] is False
    assert updated["next_run_at"] is None

    assert automations.delete_automation(item["id"]) is True
    assert automations.get_automation(item["id"]) is None


def test_agent_automation_requires_prompt(isolated_automations):
    with pytest.raises(ValueError, match="require a prompt"):
        automations.create_automation({
            "name": "Broken",
            "kind": "agent",
            "schedule": {"type": "manual", "timezone": "UTC"},
        })


def test_model_scout_can_be_promptless(isolated_automations):
    item = automations.create_automation({
        "name": "Scout",
        "kind": "model_scout",
        "schedule": {"type": "manual", "timezone": "UTC"},
    })
    assert item["prompt"] == ""


def test_schedule_calculation_hourly_daily_weekly(isolated_automations):
    after = ts(2026, 9, 29, 8, 30)  # Tuesday

    hourly = {
        "enabled": True,
        "schedule_type": "hourly",
        "schedule_minute": 45,
        "timezone": "UTC",
    }
    assert automations.next_run_at(hourly, after=after) == ts(2026, 9, 29, 8, 45)

    daily = {
        "enabled": True,
        "schedule_type": "daily",
        "schedule_time": "09:15",
        "timezone": "UTC",
    }
    assert automations.next_run_at(daily, after=after) == ts(2026, 9, 29, 9, 15)
    assert automations.next_run_at(daily, after=ts(2026, 9, 29, 10)) == ts(2026, 9, 30, 9, 15)

    weekly = {
        "enabled": True,
        "schedule_type": "weekly",
        "schedule_time": "10:00",
        "schedule_weekday": 6,
        "timezone": "UTC",
    }
    assert automations.next_run_at(weekly, after=after) == ts(2026, 10, 4, 10)


def test_due_claim_is_persistent_and_non_overlapping(isolated_automations, monkeypatch):
    base = ts(2026, 9, 29, 8, 30)
    monkeypatch.setattr(automations, "_now", lambda: base)
    item = automations.create_automation({
        "name": "Hourly check",
        "kind": "model_scout",
        "schedule": {
            "type": "hourly",
            "minute": 31,
            "timezone": "UTC",
        },
    })
    assert item["next_run_at"] == ts(2026, 9, 29, 8, 31)

    claimed = automations.claim_due(now=ts(2026, 9, 29, 8, 32))
    assert len(claimed) == 1
    assert claimed[0]["automation"]["id"] == item["id"]
    run_id = claimed[0]["run_id"]
    assert automations.get_run(run_id)["status"] == "queued"

    # The same scheduled occurrence cannot be claimed twice.
    assert automations.claim_due(now=ts(2026, 9, 29, 8, 32)) == []
    refreshed = automations.get_automation(item["id"])
    assert refreshed["next_run_at"] == ts(2026, 9, 29, 9, 31)

    running = automations.start_run(run_id)
    assert running["status"] == "running"
    finished = automations.finish_run(
        run_id,
        status="completed",
        result={"ok": True},
    )
    assert finished["status"] == "completed"
    assert finished["result"] == {"ok": True}


def test_manual_run_rejects_parallel_duplicate(isolated_automations):
    item = automations.create_automation({
        "name": "Manual check",
        "kind": "model_scout",
        "schedule": {"type": "manual", "timezone": "UTC"},
    })
    first = automations.create_run(item["id"])
    assert first["status"] == "queued"

    with pytest.raises(RuntimeError, match="already running"):
        automations.create_run(item["id"])

    automations.finish_run(first["id"], status="failed", error="test")
    second = automations.create_run(item["id"])
    assert second["id"] != first["id"]


def test_paused_schedule_has_no_next_run(isolated_automations):
    payload = {
        "enabled": False,
        "schedule_type": "daily",
        "schedule_time": "09:00",
        "timezone": "UTC",
    }
    assert automations.next_run_at(payload, after=ts(2026, 9, 29, 8)) is None
