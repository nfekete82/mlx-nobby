# Energy monitor (optional)

The energy monitor is a low-overhead host collector. It does not load AI models,
use root privileges, change runtime profiles, start benchmarks, or restart
existing MLX services. Disabled until explicitly installed.

## Requirements

- Apple Silicon macOS on the host, not in Docker.
- A recent macmon (https://github.com/vladkens/macmon) installed with Homebrew.
- Python 3 with sqlite3 (no new pip dependencies).

First inspect the live sensor:

    brew install macmon
    macmon pipe -s 2 -i 10000

Verify a nonzero sys_power field; do not proceed if the field is missing or
unsupported. Recent macmon versions include fixes for M5 Max.

## Install and control

From the repository root on the host:

    python3 -m agent.energy_monitor install
    python3 -m agent.energy_monitor status
    python3 -m agent.energy_monitor uninstall

Installation checks macmon, writes a user LaunchAgent at
~/Library/LaunchAgents/de.nobby.mlx-energy-logger.plist, and starts it in
the current user session. No root, no extra server port, no AI restarts.
An existing plist is never overwritten. Uninstall stops the service but
preserves history. After moving the repository, uninstall and reinstall.

For debugging without launchd:

    python3 -m agent.energy_monitor run

The SQLite database is kept under
~/.config/mlx-web/energy/measurements.sqlite3 (private permissions).

## UI and API

Open the existing chat Settings → System Health and scroll to
Energie · Apple Silicon. The panel displays currently observed W, measured
energy and price for today, observation hours, daily bars and the most
recent hour-by-hour usage. It polls every 30 seconds only when visible.

- Host Agent: GET /api/system/energy (8010).
- Web proxy: GET /api/mlx/system/energy (8090).

The APIs are read-only and return no local paths or prompts. The default
electricity price is 0.30 EUR/kWh. Override MLX_ENERGY_EUR_PER_KWH in the
host Agent environment, then reload the Agent during a maintenance window.
There is no editable price setting in the UI yet.

## Measurement limits

- sys_power is internal Mac system power, not wall power. AC adapter losses
  and battery charging require an external plug meter to measure.
- Component watts (CPU/GPU/ANE) are included in system power. Never add
  them to sys_power.
- Each valid sample is integrated over only its own observed interval.
  Sleep and missed periods are not extrapolated.
- Unsupported/nonpositive sys_power readings are ignored instead of
  manufacturing a total from CPU/GPU/ANE.
- 30-day retention; no media, model names or prompt data collected.
- Per-job and per-model energy attribution is deliberately not included
  yet; background power and overlapping workloads prevent exact allocation.

CPU-only checks:

    python3 -m pytest -q tests/test_energy_monitor.py
    node --check frontend/assets/chat/energy-monitor.js

Before publishing a new release, run the full local release and browser gates
and a real macmon M5 Max sensor test. The collector has not been validated
against the live hardware by a GitHub-only integration.
