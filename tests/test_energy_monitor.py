"""CPU-only energy sampling and math regression tests (no macmon required)."""
import sqlite3
import time

from agent import energy_monitor as power


def frame(end, watts=72.0):
    return {
        "timestamp": __import__("datetime").datetime.fromtimestamp(
            end, __import__("datetime").timezone.utc
        ).isoformat(),
        "sys_power": watts,
        "cpu_power": 20,
        "gpu_power": 30,
        "ane_power": 0,
        "temp": {"cpu_temp_avg": 52},
        "memory": {"swap_usage": 1073741824},
    }


def test_sample_requires_whole_system_power():
    now = time.time()
    assert power.normalize({"cpu_power": 80, "gpu_power": 50}, now=now) is None
    assert power.normalize(frame(now, 0), now=now) is None
    sample = power.normalize(frame(now, 72), now=now)
    assert sample["watts"] == 72
    assert sample["cpu_w"] == 20
    assert sample["temp_c"] == 52


def test_integrates_only_observed_windows_no_sleep_gap(tmp_path):
    path = tmp_path / "energy.sqlite3"
    connection = power._connect(path, create=True)
    now = time.time() - 10
    a = power.normalize(frame(now - 3600), now=now)
    b = power.normalize(frame(now - 3590), now=now)
    c = power.normalize(frame(now), now=now)
    assert power.store_sample(connection, a, 10000)
    assert power.store_sample(connection, b, 10000, a["end"])
    assert power.store_sample(connection, c, 10000, b["end"])
    assert not power.store_sample(connection, c, 10000, c["end"])
    rows = connection.execute("SELECT wh FROM samples ORDER BY end_ts").fetchall()
    connection.close()
    assert len(rows) == 3
    assert all(abs(row[0] - 0.2) < 1e-7 for row in rows)
    report = power.snapshot(path, now=now + 1, price_eur_kwh=0.30)
    assert report["current_w"] == 72
    assert report["active"]
    assert report["source"] == "macmon.sys_power"
    assert abs(report["seven_days_kwh"] - 0.0006) < 1e-6
    assert report["today_measured_hours"] <= 3 * 10 / 3600 + 1e-4


def test_empty_database_returns_no_fake_values(tmp_path):
    report = power.snapshot(tmp_path / "not-created.sqlite3")
    assert report["current_w"] is None
    assert report["today_kwh"] == 0
    assert report["today_measured_hours"] == 0
    assert not report["active"]


def test_energy_route_contract(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent import energy_routes

    monkeypatch.setattr(energy_routes, "snapshot", lambda: {"ok": True, "current_w": None})
    app = FastAPI()
    energy_routes.install_routes(app)
    assert TestClient(app).get("/api/system/energy").json() == {
        "ok": True, "current_w": None
    }


def test_web_energy_proxy():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend import energy_routes

    calls = []
    def forward(method, path, **kwargs):
        calls.append((method, path))
        return {"today_kwh": 0.2}
    app = FastAPI()
    energy_routes.install_routes(app, forward)
    assert TestClient(app).get("/api/mlx/system/energy").json() == {
        "today_kwh": 0.2
    }
    assert calls == [("GET", "/api/system/energy")]
