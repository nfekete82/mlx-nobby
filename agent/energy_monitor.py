"""Optional Apple Silicon energy logger using macmon; no model or runtime changes.

All watt measurements are internal system/SoC readings, NOT AC wall power.
The SQLite database stays on the host, outside Git and Docker.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import math
import os
from pathlib import Path
import plistlib
import shutil
import signal
import sqlite3
import subprocess
import sys
import time

DEFAULT_INTERVAL_MS = 10000
RETENTION_DAYS = 30
DB_PATH = Path.home() / ".config/mlx-web/energy/measurements.sqlite3"
PLIST_PATH = Path.home() / "Library/LaunchAgents/de.nobby.mlx-energy-logger.plist"
LABEL = "de.nobby.mlx-energy-logger"
PROJECT_DIR = Path(__file__).resolve().parents[1]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0 else None


def normalize(raw, now=None):
    """Parse a macmon JSON frame. Never substitute component power for sys_power."""
    if not isinstance(raw, dict):
        return None
    power = _number(raw.get("sys_power"))
    # On unsupported virtual machines/counters zero can mean no measurement.
    if power is None or power <= 0 or power > 500:
        return None
    try:
        end = datetime.fromisoformat(str(raw["timestamp"]).replace("Z", "+00:00")).timestamp()
    except (KeyError, TypeError, ValueError, OverflowError):
        end = float(now if now is not None else time.time())
    if not math.isfinite(end) or end <= 0 or end > time.time() + 600:
        return None
    temp = raw.get("temp") if isinstance(raw.get("temp"), dict) else {}
    memory = raw.get("memory") if isinstance(raw.get("memory"), dict) else {}
    return {
        "end": end,
        "watts": power,
        "cpu_w": _number(raw.get("cpu_power")),
        "gpu_w": _number(raw.get("gpu_power")),
        "ane_w": _number(raw.get("ane_power")),
        "ram_w": _number(raw.get("ram_power")),
        "temp_c": _number(temp.get("cpu_temp_avg")),
        "swap_bytes": _number(memory.get("swap_usage")),
    }


def _connect(path=DB_PATH, *, create=False):
    path = Path(path)
    if create:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
    elif not path.is_file():
        return None
    connection = sqlite3.connect(str(path), timeout=3)
    connection.execute("PRAGMA busy_timeout=3000")
    if create:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS samples ("
            "end_ts REAL PRIMARY KEY, start_ts REAL NOT NULL, "
            "watts REAL NOT NULL, wh REAL NOT NULL, "
            "cpu_w REAL, gpu_w REAL, ane_w REAL, ram_w REAL, "
            "temp_c REAL, swap_bytes REAL)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS samples_start ON samples(start_ts)")
        connection.commit()
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return connection


def store_sample(db, sample, interval_ms=DEFAULT_INTERVAL_MS, previous_end=None):
    """Integrate only observed intervals; gaps from sleep are NEVER interpolated."""
    period = max(1.0, min(60.0, interval_ms / 1000.0))
    end = sample["end"]
    start = end - period
    if previous_end is not None and 0 < end - previous_end <= period * 1.5:
        start = max(start, previous_end)
    elif previous_end is not None and end <= previous_end:
        return False
    wh = sample["watts"] * (end - start) / 3600.0
    with db:
        result = db.execute(
            "INSERT OR IGNORE INTO samples "
            "(end_ts,start_ts,watts,wh,cpu_w,gpu_w,ane_w,ram_w,temp_c,swap_bytes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (end, start, sample["watts"], wh, sample["cpu_w"], sample["gpu_w"],
             sample["ane_w"], sample["ram_w"], sample["temp_c"], sample["swap_bytes"]),
        )
    return result.rowcount == 1


def snapshot(path=DB_PATH, *, now=None, price_eur_kwh=None):
    """Read-only history, with measured coverage and no fictional extrapolation."""
    now = float(time.time() if now is None else now)
    if price_eur_kwh is None:
        try:
            price_eur_kwh = float(os.environ.get("MLX_ENERGY_EUR_PER_KWH", "0.30"))
        except (TypeError, ValueError, OverflowError):
            price_eur_kwh = 0.30
    price = _number(price_eur_kwh)
    if price is None or price > 10:
        price = 0.30
    today = datetime.fromtimestamp(now).astimezone().date()
    first_day = today - timedelta(days=6)
    start = datetime.combine(first_day, datetime.min.time()).astimezone().timestamp()
    daily = {str(first_day + timedelta(days=i)): {"wh": 0.0, "hours": 0.0}
             for i in range(7)}
    hourly = {}
    latest = None
    path = Path(path)
    conn = _connect(path)
    if conn is not None:
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM samples ORDER BY end_ts DESC LIMIT 1"
            ).fetchone()
            if row:
                latest = dict(row)
            rows = conn.execute(
                "SELECT start_ts,end_ts,watts FROM samples "
                "WHERE end_ts > ? AND start_ts < ? ORDER BY start_ts",
                (start, now),
            ).fetchall()
            for row in rows:
                s = max(float(row["start_ts"]), start)
                e = min(float(row["end_ts"]), now)
                if e <= s:
                    continue
                # Split at local midnight/hour boundaries for DST-safe totals.
                while s < e:
                    dt = datetime.fromtimestamp(s).astimezone()
                    day = str(dt.date())
                    # Epoch-hour buckets remain monotonic through DST fall-back;
                    # midnight is computed in the system's local timezone.
                    next_hour_ts = (math.floor(s / 3600) + 1) * 3600
                    next_midnight_ts = datetime.combine(
                        dt.date() + timedelta(days=1), datetime.min.time()
                    ).astimezone().timestamp()
                    stop = min(e, next_hour_ts, next_midnight_ts)
                    if stop <= s:
                        stop = min(e, s + 3600)
                    duration = stop - s
                    wh = float(row["watts"]) * duration / 3600
                    if day in daily:
                        daily[day]["wh"] += wh
                        daily[day]["hours"] += duration / 3600
                    key = dt.strftime("%Y-%m-%d %H:00 %z")
                    value = hourly.setdefault(key, {"wh": 0.0, "hours": 0.0, "time": s})
                    value["wh"] += wh
                    value["hours"] += duration / 3600
                    s = stop
        finally:
            conn.close()
    fresh = bool(latest and 0 <= now - latest["end_ts"] <= 35)
    today_item = daily.get(str(today), {"wh": 0.0, "hours": 0.0})
    total_wh = sum(item["wh"] for item in daily.values())
    return {
        "ok": True,
        "source": "macmon.sys_power",
        "meaning": "internal_system_power_not_wall_power",
        "active": fresh,
        "last_sample_at": latest["end_ts"] if latest else None,
        "current_w": round(latest["watts"], 2) if fresh else None,
        "cpu_w": round(latest["cpu_w"], 2) if fresh and latest["cpu_w"] is not None else None,
        "gpu_w": round(latest["gpu_w"], 2) if fresh and latest["gpu_w"] is not None else None,
        "ane_w": round(latest["ane_w"], 2) if fresh and latest["ane_w"] is not None else None,
        "temperature_c": round(latest["temp_c"], 1) if fresh and latest["temp_c"] is not None else None,
        "today_kwh": round(today_item["wh"] / 1000, 5),
        "today_eur": round(today_item["wh"] / 1000 * price, 4),
        "today_measured_hours": round(today_item["hours"], 3),
        "seven_days_kwh": round(total_wh / 1000, 5),
        "price_eur_kwh": price,
        "days": [{"date": key, "kwh": round(value["wh"] / 1000, 5),
                  "measured_hours": round(value["hours"], 3)}
                 for key, value in daily.items()],
        "hours": [{"hour": key, "wh": round(value["wh"], 3),
                   "measured_hours": round(value["hours"], 3)}
                  for key, value in sorted(hourly.items(), key=lambda pair: pair[1]["time"])[-24:]],
    }


def run(macmon, interval_ms):
    db = _connect(DB_PATH, create=True)
    if db is None:
        raise RuntimeError("energy database unavailable")
    command = [macmon, "pipe", "-i", str(interval_ms)]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )
    def terminate(_signum, _frame):
        process.terminate()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    # Preserve the last recorded boundary across launcher restarts.
    last = db.execute("SELECT MAX(end_ts) FROM samples").fetchone()
    previous_end = last[0] if last else None
    count = 0
    try:
        for line in process.stdout:
            if len(line) > 120_000:
                continue
            try:
                sample = normalize(json.loads(line))
            except (json.JSONDecodeError, UnicodeError):
                continue
            if not sample:
                continue
            if store_sample(db, sample, interval_ms, previous_end):
                previous_end = sample["end"]
                count += 1
                if count % 360 == 0:
                    with db:
                        db.execute("DELETE FROM samples WHERE end_ts < ?",
                                   (time.time() - RETENTION_DAYS * 86400,))
        return process.wait() or 1
    finally:
        if process.poll() is None:
            process.terminate()
        db.close()


def install(interval_ms):
    if sys.platform != "darwin":
        raise RuntimeError("macOS required")
    macmon = shutil.which("macmon")
    if not macmon:
        raise RuntimeError("macmon missing; install first: brew install macmon")
    if PLIST_PATH.exists():
        raise RuntimeError("energy logger already installed; uninstall before reinstall")
    if not 1000 <= interval_ms <= 60000:
        raise ValueError("interval must be 1000..60000 ms")
    DB_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable, "-m", "agent.energy_monitor", "run",
            "--macmon", macmon, "--interval", str(interval_ms),
        ],
        "WorkingDirectory": str(PROJECT_DIR),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": str(DB_PATH.parent / "logger-stderr.log"),
    }
    PLIST_PATH.write_bytes(plistlib.dumps(plist))
    PLIST_PATH.chmod(0o600)
    result = subprocess.run(
        ["launchctl", "bootstrap", "gui/" + str(os.getuid()), str(PLIST_PATH)],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        PLIST_PATH.unlink()
        raise RuntimeError("launchctl bootstrap failed (no services changed)")
    print("Energy logger installed; data: " + str(DB_PATH))


def uninstall():
    if not PLIST_PATH.exists():
        print("Energy logger is not installed")
        return
    subprocess.run(
        ["launchctl", "bootout", "gui/" + str(os.getuid()), str(PLIST_PATH)],
        check=False, capture_output=True,
    )
    PLIST_PATH.unlink()
    print("Energy logger removed; measured history preserved.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Optional local MLX Nobby energy logger")
    parser.add_argument("action", choices=["run", "install", "uninstall", "status"])
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_MS)
    parser.add_argument("--macmon", default=None)
    args = parser.parse_args(argv)
    if args.action == "install":
        install(args.interval)
    elif args.action == "uninstall":
        uninstall()
    elif args.action == "status":
        print(json.dumps(snapshot(), indent=2))
    else:
        macmon = args.macmon or shutil.which("macmon")
        if not macmon:
            parser.error("macmon missing; brew install macmon")
        if not 1000 <= args.interval <= 60000:
            parser.error("interval must be 1000..60000 ms")
        return run(macmon, args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
