#!/usr/bin/env python3

import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path


PORT = 8020
LIMIT_GB = 6.0
LIMIT_BYTES = int(LIMIT_GB * 1024**3)
REQUIRED_HITS = 2
CHECK_INTERVAL = 300

SERVICE_LABEL = "de.nobby.mlx-embeddings"
LOG_FILE = Path.home() / ".config" / "mlx-web" / "embedding-watchdog.log"


def log(message):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"

    print(line, flush=True)

    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def find_pid():
    result = subprocess.run(
        [
            "lsof",
            "-nP",
            f"-iTCP:{PORT}",
            "-sTCP:LISTEN",
            "-t",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        line = line.strip()

        if line.isdigit():
            return int(line)

    return None


def physical_footprint(pid):
    result = subprocess.run(
        ["vmmap", "-summary", str(pid)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    match = re.search(
        r"Physical footprint:\s+([0-9.]+)([KMG])",
        result.stdout,
    )

    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2)

    factors = {
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
    }

    return int(value * factors[unit])


def restart_service():
    uid = os.getuid()

    result = subprocess.run(
        [
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{uid}/{SERVICE_LABEL}",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or
            result.stdout.strip() or
            "launchctl kickstart fehlgeschlagen"
        )


def format_gb(value):
    return value / 1024**3


def main():
    hits = 0

    log(
        f"Watchdog gestartet · Port {PORT} · "
        f"Limit {LIMIT_GB:.1f} GB · "
        f"{REQUIRED_HITS} Treffer erforderlich"
    )

    while True:
        try:
            pid = find_pid()

            if pid is None:
                hits = 0
                log(
                    "Embedding-Service läuft nicht – "
                    "LaunchAgent übernimmt den Neustart."
                )

            else:
                footprint = physical_footprint(pid)

                if footprint is None:
                    log(
                        f"PID {pid}: Physical Footprint "
                        "konnte nicht ermittelt werden."
                    )

                elif footprint > LIMIT_BYTES:
                    hits += 1

                    log(
                        f"PID {pid}: {format_gb(footprint):.2f} GB "
                        f"> {LIMIT_GB:.1f} GB "
                        f"({hits}/{REQUIRED_HITS})"
                    )

                    if hits >= REQUIRED_HITS:
                        log(
                            f"Speicherlimit dauerhaft überschritten – "
                            f"{SERVICE_LABEL} wird neu gestartet."
                        )

                        restart_service()

                        hits = 0

                        log("Embedding-Service neu gestartet.")

                else:
                    if hits:
                        log(
                            f"PID {pid}: wieder normal bei "
                            f"{format_gb(footprint):.2f} GB."
                        )

                    hits = 0

        except Exception as exc:
            log(f"Watchdog-Fehler: {exc}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
