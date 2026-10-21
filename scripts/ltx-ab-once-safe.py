#!/usr/bin/env python3
"""One approved, guarded LTX 0.16.3/0.17.0 A/B run; restore LaunchAgents."""
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Running "python scripts/..." sets sys.path[0] to scripts/, not the repository.
# Add only our trusted repository root for runtime_coordinator imports.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DOMAIN = "gui/" + str(os.getuid())
SERVICES = (("de.nobby.musetalk", 8070), ("de.nobby.mlx-router", 8040))
stopped = []


def sh(*args):
    return subprocess.run(args, text=True, capture_output=True)


def loaded(label):
    return sh("launchctl", "print", f"{DOMAIN}/{label}").returncode == 0


def health(port, endpoint="/health"):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{endpoint}", timeout=5) as response:
            return json.load(response)
    except Exception:
        return None


def stop_service(label, port):
    if not loaded(label):
        if health(port) is not None:
            raise RuntimeError(f"{label}: läuft ohne kontrollierbaren LaunchAgent")
        print(f"  {label}: bereits gestoppt", flush=True)
        return
    plist = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    if not plist.is_file():
        raise RuntimeError(f"Wiederherstellungs-LaunchAgent fehlt: {plist}")
    stopped.append(label)
    result = sh("launchctl", "bootout", f"{DOMAIN}/{label}")
    if result.returncode:
        raise RuntimeError(f"{label}: bootout fehlgeschlagen: {result.stderr.strip()}")
    for _ in range(40):
        if health(port) is None:
            print(f"  {label}: kontrolliert angehalten", flush=True)
            return
        time.sleep(0.5)
    raise RuntimeError(f"{label}: Port {port} nach bootout noch erreichbar")


def restore():
    print("\n=== DIENSTE WIEDERHERSTELLEN ===", flush=True)
    for label in reversed(stopped):
        if loaded(label):
            print(f"  {label}: bereits registriert", flush=True)
            continue
        plist = Path.home() / "Library/LaunchAgents" / (label + ".plist")
        result = sh("launchctl", "bootstrap", DOMAIN, str(plist))
        if result.returncode:
            print(f"  WARNUNG: {label} nicht wiederhergestellt: {result.stderr.strip()}")
            print(f"  Manuell: launchctl bootstrap {DOMAIN} {plist}")
        else:
            print(f"  {label}: wieder gestartet (Gewichte laden ggf. noch)", flush=True)
    print("  Speech bleibt erreichbar; das Klonmodell lädt bei Bedarf erneut.", flush=True)


def check_no_jobs():
    import runtime_coordinator
    lease = runtime_coordinator.lease_state_snapshot()
    if lease.get("active") or lease.get("waiting_count"):
        raise RuntimeError("Ein koordinierter KI-Auftrag ist aktiv oder wartet")
    video = health(8060)
    if not isinstance(video, dict) or video.get("active_generation") is not False or video.get("active_job_id"):
        raise RuntimeError("Video-Service nicht eindeutig frei")
    speech = health(8050)
    if not isinstance(speech, dict) or speech.get("active_generation") is not False:
        raise RuntimeError("Speech-Service nicht eindeutig frei")
    router = health(8040)
    if router is not None:
        metrics = health(8040, "/metrics")
        summary = (metrics or {}).get("summary") or {}
        server = (metrics or {}).get("server") or {}
        if not summary or summary.get("in_flight") != 0 or server.get("request_queue_depth") != 0 or server.get("audio_queue_depth") != 0:
            raise RuntimeError("Router nicht eindeutig idle; kein Stopp")
    muse = health(8070)
    if isinstance(muse, dict) and (muse.get("active_generation") is True or muse.get("busy") is True):
        raise RuntimeError("MuseTalk verarbeitet gerade einen Auftrag")
    return speech


def preflight():
    result = sh(sys.executable, "-B", "scripts/benchmark-ltx-video.py", "--isolated", "--preflight")
    if result.returncode:
        raise RuntimeError("LTX-Preflight fehlgeschlagen: " + result.stderr[-700:])
    data = json.loads(result.stdout)
    available = data.get("snapshot", {}).get("available_estimate_bytes", 0) / 1024**3
    print(f"  Verfügbarer RAM (Schätzung): {available:.2f} GiB", flush=True)
    print("  Freigabe:", data.get("allowed"), "Gründe:", data.get("reasons"), flush=True)
    if data.get("allowed") is not True:
        raise RuntimeError("Sicherheitsprüfung verweigert; kein GPU-Test")


def run_benchmark():
    cmd = [sys.executable, "-B", "scripts/benchmark-ltx-video.py", "--isolated",
           "--versions", "0.16.3", "0.17.0", "--profiles", "production-control",
           "--seed", "42", "--width", "1280", "--height", "704",
           "--frames", "121", "--fps", "24", "--warm-runs", "0",
           "--execute", "--approve-gpu"]
    child = subprocess.Popen(cmd, start_new_session=True)
    try:
        result = child.wait()
        if result:
            raise RuntimeError(f"Benchmark fehlgeschlagen (Exit {result})")
    except BaseException:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
            try:
                child.wait(timeout=45)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=10)
        raise


def require_guarded_lab():
    """Fail *before* stopping any services unless the admission contract is present.

    The old one-shot helper has no durable exclusive session spanning its
    child, interruption and LaunchAgent recovery. A read-only proof snapshot
    is NOT authorization to proceed, even if every server reports healthy.
    The managed lab controller is the only intended owner of that fence.
    """
    try:
        from ltx_lab.admission import Gate
        from ltx_lab.exclusive import verify_services
    except ImportError as exc:
        raise RuntimeError(
            "Die vollständige lokale Admission-Implementierung fehlt. "
            "Keine Dienste werden gestoppt; erst das sichere LTX-Labor "
            "vollständig integrieren."
        ) from exc
    try:
        verify_services(Gate())
    except Exception as exc:
        raise RuntimeError(
            "Admission-Deployment nicht verifiziert (z. B. /lab/admission 404). "
            "Keine Dienste werden gestoppt: " + str(exc)
        ) from exc
    raise RuntimeError(
        "Admission-Nachweise sind vorhanden, aber dieses ältere One-Shot-Skript "
        "besitzt keine durchgängige exklusive Gate-/Recovery-Sitzung. "
        "Bitte den abgesicherten LTX-Laborcontroller verwenden; "
        "kein ungesicherter automatischer Dienststopp."
    )


def main():
    os.chdir(ROOT)
    print("=== LTX 0.16.3 vs 0.17.0 – Admission-Prüfung ===", flush=True)
    require_guarded_lab()
    # The original workflow below is intentionally unreachable until it can
    # be replaced with a durable, Gate-owned, restore-verified transaction.
    print("Währenddessen keine weiteren KI-Jobs oder Chats starten.", flush=True)
    for label, port in SERVICES:
        if health(port) is not None and not loaded(label):
            raise RuntimeError(f"{label}: aktiver Dienst ohne kontrollierbaren LaunchAgent")
    print("\n1. Aktive Jobs prüfen", flush=True)
    speech = check_no_jobs()

    import runtime_coordinator
    lock_path = Path(runtime_coordinator.LOCK_PATH)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Runtime-Lease belegt; kein Dienst wird gestoppt") from exc
        try:
            check_no_jobs()
            print("\n2. MuseTalk und Router kontrolliert anhalten", flush=True)
            for label, port in SERVICES:
                stop_service(label, port)
            print("\n3. Speech-Modell entladen", flush=True)
            if any(speech.get(key) is True for key in ("loaded", "tts_loaded", "tts_clone_loaded")):
                req = urllib.request.Request(
                    "http://127.0.0.1:8050/unload", data=b"{}", method="POST",
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=90) as response:
                    result = json.load(response)
                after = health(8050)
                if result.get("ok") is not True or not isinstance(after, dict) or any(
                    after.get(key) is True for key in ("loaded", "tts_loaded", "tts_clone_loaded")
                ):
                    raise RuntimeError("Speech-Unload nicht bestätigt")
                print("  Speech-Gewichte freigegeben; Lana Weiss bleibt gespeichert", flush=True)
            else:
                print("  Speech-Gewichte bereits entladen", flush=True)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

    print("\n4. Sicherheitsfreigabe", flush=True)
    preflight()
    print("\n5. A/B-Videogenerierung: je ein 5-Sekunden-Clip", flush=True)
    run_benchmark()
    print("\nA/B abgeschlossen – Resultate unter .ltx-lab/results/", flush=True)


def interrupted(signum, _frame):
    raise KeyboardInterrupt(f"Signal {signum}")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except BaseException as exc:
        print("\nABBRUCH:", exc, file=sys.stderr, flush=True)
        sys.exit(1)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        restore()
