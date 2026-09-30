#!/usr/bin/env python3
"""Benchmark Nobby's stable MPS and native-MLX LTX backends."""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


DEFAULT_MODELS = ["ltx-2.5-22b-distilled", "ltx-2.5-mlx-q4"]
TERMINAL = {"completed", "failed", "cancelled"}
HEARTBEAT_SECONDS = 30.0
THERMAL_RANK = {
    "Nominal": 0,
    "Moderate": 1,
    "Heavy": 2,
    "Trapping": 3,
}


def request_json(method, url, payload=None, timeout=30):
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def reset_mlx_runtime(base_url):
    result = request_json(
        "POST",
        base_url.rstrip("/") + "/runtime/mlx/reset",
        {},
        timeout=30,
    )
    if not result.get("ok"):
        raise RuntimeError("MLX-Runtime konnte nicht zurückgesetzt werden")
    return result


def gb(value):
    if not isinstance(value, (int, float)):
        return None
    return round(float(value) / (1024 ** 3), 2)


def elapsed_text(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _command_output(command, timeout=5):
    """Return best-effort local diagnostic output without breaking benchmarks."""
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _sysctl_output(name):
    """Read a sysctl value even when /usr/sbin is missing from PATH."""
    for executable in ("/usr/sbin/sysctl", "sysctl"):
        output = _command_output([executable, "-n", name])
        if output:
            return output
    return ""


def _vm_stat_ram_used(output):
    page_size_match = re.search(r"page size of (\d+) bytes", output or "")
    if not page_size_match:
        return None
    page_size = int(page_size_match.group(1))
    pages = {}
    for label, value in re.findall(r"^([^:]+):\s+(\d+)\.", output or "", re.MULTILINE):
        pages[label] = int(value)
    used_pages = sum(pages.get(label, 0) for label in (
        "Pages active",
        "Pages inactive",
        "Pages wired down",
        "Pages occupied by compressor",
        "Pages speculative",
    ))
    return used_pages * page_size


def _swap_used(output):
    match = re.search(
        r"used\s*=\s*([0-9.]+)\s*([KMGT]?)(?:i?B)?",
        output or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    power = {"": 0, "K": 1, "M": 2, "G": 3, "T": 4}.get(match.group(2).upper())
    if power is None:
        return None
    return int(float(match.group(1)) * (1024 ** power))


def _parse_thermal_limits(output):
    """Parse `pmset -g therm` limits; these are limits, not temperatures."""
    parsed = {
        "cpu_speed_limit": None,
        "scheduler_limit": None,
        "available_cpus": None,
        "thermal_warning_recorded": None,
        "performance_warning_recorded": None,
    }
    text = output or ""
    lower = text.lower()
    if "no thermal warning level has been recorded" in lower:
        parsed["thermal_warning_recorded"] = False
    elif "thermal warning level" in lower:
        parsed["thermal_warning_recorded"] = True
    if "no performance warning level has been recorded" in lower:
        parsed["performance_warning_recorded"] = False
    elif "performance warning level" in lower:
        parsed["performance_warning_recorded"] = True

    for key, field in (
        ("CPU_Speed_Limit", "cpu_speed_limit"),
        ("Scheduler_Limit", "scheduler_limit"),
        ("Available_CPUs", "available_cpus"),
    ):
        match = re.search(rf"{re.escape(key)}\s*=\s*(\d+)", text)
        if match:
            parsed[field] = int(match.group(1))
    return parsed


def _memory_pressure_name(value):
    return {1: "normal", 2: "warning", 4: "critical"}.get(
        value, str(value) if value is not None else "n/a"
    )


def system_snapshot():
    """Capture cheap system-wide macOS telemetry outside benchmark wall time."""
    vm_stat = _command_output(["vm_stat"])
    swap = _sysctl_output("vm.swapusage")
    therm = _command_output(["pmset", "-g", "therm"])
    pressure_raw = _sysctl_output("kern.memorystatus_vm_pressure_level")
    try:
        pressure = int(pressure_raw.strip()) if pressure_raw else None
    except ValueError:
        pressure = None
    return {
        "captured_at": time.time(),
        "ram_used_bytes": _vm_stat_ram_used(vm_stat),
        "swap_used_bytes": _swap_used(swap),
        "memory_pressure_level": pressure,
        "thermal": _parse_thermal_limits(therm),
    }


def system_snapshot_text(snapshot):
    ram = gb(snapshot.get("ram_used_bytes"))
    swap = gb(snapshot.get("swap_used_bytes"))
    thermal = snapshot.get("thermal") or {}
    parts = [
        f"RAM {ram:.1f} GB" if ram is not None else "RAM n/a",
        f"Swap {swap:.1f} GB" if swap is not None else "Swap n/a",
        f"Pressure {_memory_pressure_name(snapshot.get('memory_pressure_level'))}",
    ]
    cpu_limit = thermal.get("cpu_speed_limit")
    scheduler_limit = thermal.get("scheduler_limit")
    available_cpus = thermal.get("available_cpus")
    if cpu_limit is not None:
        parts.append(f"CPU-Limit {cpu_limit}%")
    if scheduler_limit is not None:
        parts.append(f"Scheduler {scheduler_limit}%")
    if available_cpus is not None:
        parts.append(f"CPUs {available_cpus}")
    if thermal.get("thermal_warning_recorded") is False:
        parts.append("Thermal-Warnung nein")
    elif thermal.get("thermal_warning_recorded") is True:
        parts.append("Thermal-Warnung ja")
    if thermal.get("performance_warning_recorded") is False:
        parts.append("Performance-Warnung nein")
    elif thermal.get("performance_warning_recorded") is True:
        parts.append("Performance-Warnung ja")
    return " · ".join(parts)


def _parse_powermetrics_thermal(output):
    levels = [
        value.title()
        for value in re.findall(
            r"Current pressure level:\s*([A-Za-z]+)",
            output or "",
            re.IGNORECASE,
        )
    ]
    counts = {}
    for level in levels:
        counts[level] = counts.get(level, 0) + 1
    peak = None
    if levels:
        peak = max(levels, key=lambda value: THERMAL_RANK.get(value, -1))
    return {
        "samples": len(levels),
        "first": levels[0] if levels else None,
        "last": levels[-1] if levels else None,
        "peak": peak,
        "counts": counts,
    }


def _thermal_trace_text(trace):
    if not trace or not trace.get("samples"):
        return "keine Thermal-Samples"
    counts = trace.get("counts") or {}
    durations = " · ".join(
        f"{counts[level]}× {level}"
        for level in ("Nominal", "Moderate", "Heavy", "Trapping")
        if counts.get(level)
    )
    return (
        f"{trace.get('first') or '?'} → {trace.get('last') or '?'} "
        f"· Peak {trace.get('peak') or '?'}"
        + (f" · {durations}" if durations else "")
    )


def _thermal_trace_compact(trace):
    if not trace or not trace.get("samples"):
        return "—"
    counts = trace.get("counts") or {}
    parts = []
    for level, short in (
        ("Nominal", "N"),
        ("Moderate", "M"),
        ("Heavy", "H"),
        ("Trapping", "T"),
    ):
        if counts.get(level):
            parts.append(f"{short}{counts[level]}")
    return "/".join(parts) or "—"


def _thermal_flow(trace):
    if not trace or not trace.get("samples"):
        return "—"
    short = {
        "Nominal": "N",
        "Moderate": "M",
        "Heavy": "H",
        "Trapping": "T",
    }
    first = short.get(trace.get("first"), "?")
    peak = short.get(trace.get("peak"), "?")
    last = short.get(trace.get("last"), "?")
    return f"{first}→{peak}→{last}"


def _prepare_thermal_sampling():
    if sys.platform != "darwin":
        raise RuntimeError("--thermal benötigt macOS")
    if not os.path.exists("/usr/bin/powermetrics"):
        raise RuntimeError("/usr/bin/powermetrics wurde nicht gefunden")
    print(
        "Thermal-Telemetrie: sudo wird einmal vorbereitet; "
        "powermetrics läuft danach automatisch pro Benchmark.",
        flush=True,
    )
    completed = subprocess.run(["sudo", "-v"], check=False)
    if completed.returncode != 0:
        raise RuntimeError("sudo-Freigabe für powermetrics fehlgeschlagen")


def _start_thermal_sampler(enabled):
    if not enabled:
        return None
    log = tempfile.NamedTemporaryFile(
        mode="w+",
        encoding="utf-8",
        prefix="mlx-nobby-thermal-",
        suffix=".log",
        delete=False,
    )
    try:
        process = subprocess.Popen(
            [
                "sudo",
                "-n",
                "/usr/bin/powermetrics",
                "-s",
                "thermal",
                "-i",
                "1000",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception:
        path = log.name
        log.close()
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return {"process": process, "log": log, "path": log.name}


def _stop_thermal_sampler(state):
    if not state:
        return None
    process = state["process"]
    log = state["log"]
    path = state["path"]
    try:
        if process.poll() is None:
            try:
                process.send_signal(signal.SIGINT)
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
        log.flush()
        log.seek(0)
        output = log.read()
    finally:
        log.close()
        try:
            os.unlink(path)
        except OSError:
            pass
    trace = _parse_powermetrics_thermal(output)
    if not trace.get("samples") and output.strip():
        trace["error"] = output.strip()[-300:]
    return trace


def progress_text(job):
    phase = str(job.get("phase") or job.get("status") or "working")
    progress = job.get("progress")
    percentage = round(progress * 100) if isinstance(progress, (int, float)) else None
    step = job.get("current_step")
    total = job.get("total_steps")
    if isinstance(step, int) and isinstance(total, int) and step > 0 and total > 0:
        suffix = f" {step}/{total}"
        if percentage is not None:
            suffix += f" ({percentage} %)"
        return phase, percentage, step, total, phase + suffix
    if percentage is not None:
        return phase, percentage, None, total, f"{phase} ({percentage} %)"
    return phase, None, None, total, phase


def _print_fast_mlx_muxing_if_missed(model, phase, last_signature, total, elapsed):
    """Surface MLX's very short final mux phase when polling skips over it."""
    if model != "ltx-2.5-mlx-q4" or phase != "completed":
        return
    previous_phase = last_signature[0] if last_signature else None
    if previous_phase in {"muxing", "completed"}:
        return
    suffix = ""
    if isinstance(total, int) and total > 0:
        suffix = f" {total}/{total}"
    print(f"    muxing{suffix} (98 %) · {elapsed_text(elapsed)}", flush=True)


def run_job(base_url, model, args, repeat):
    system_before = system_snapshot()
    print(f"    System vorher: {system_snapshot_text(system_before)}", flush=True)
    thermal_sampler = _start_thermal_sampler(args.thermal)
    thermal_trace = None
    created_at = time.monotonic()
    try:
        payload = {
            "operation": "t2v",
            "chat_id": "ltx-benchmark",
            "run_id": f"benchmark-{model}-{repeat}-{int(time.time())}",
            "chat_revision": 0,
            "payload": {
                "prompt": args.prompt,
                "model": model,
                "quality": args.quality,
                "duration": args.duration,
                "fps": args.fps,
                "seed": args.seed,
                "aspect_ratio": args.aspect_ratio,
            },
        }
        job = request_json("POST", base_url + "/jobs", payload, timeout=30)
        job_id = job["id"]
        print(f"  job {job_id}: gestartet", flush=True)

        last_signature = None
        last_output_at = created_at
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            job = request_json("GET", base_url + f"/jobs/{job_id}", timeout=15)
            now = time.monotonic()
            phase, percentage, step, total, label = progress_text(job)
            signature = (phase, percentage, step, total)
            heartbeat_due = step is None and now - last_output_at >= HEARTBEAT_SECONDS
            if signature != last_signature or heartbeat_due:
                if signature != last_signature:
                    _print_fast_mlx_muxing_if_missed(
                        model, phase, last_signature, total, now - created_at,
                    )
                print(f"    {label} · {elapsed_text(now - created_at)}", flush=True)
                last_signature = signature
                last_output_at = now
            if job.get("status") in TERMINAL:
                break
            time.sleep(args.poll)
        else:
            try:
                request_json("POST", base_url + f"/jobs/{job_id}/cancel", {}, timeout=30)
            except Exception:
                pass
            raise RuntimeError(f"Timeout nach {args.timeout:.0f} s")
        wall = round(time.monotonic() - created_at, 3)
    finally:
        thermal_trace = _stop_thermal_sampler(thermal_sampler)

    system_after = system_snapshot()
    print(f"    System nachher: {system_snapshot_text(system_after)}", flush=True)
    if args.thermal:
        print(f"    Thermal im Lauf: {_thermal_trace_text(thermal_trace)}", flush=True)
        if thermal_trace and thermal_trace.get("error"):
            print(
                f"    Thermal-Hinweis: {thermal_trace['error']}",
                file=sys.stderr,
                flush=True,
            )
    if job.get("status") != "completed":
        raise RuntimeError(job.get("error") or f"Job endete mit {job.get('status')}")

    result = job.get("result") or {}
    peak = result.get("memory_peak") or job.get("memory_peak") or {}
    before = result.get("memory_before") or job.get("memory_before") or {}
    after = result.get("memory_after") or job.get("memory_after") or {}
    system_swap_before = gb(system_before.get("swap_used_bytes"))
    system_swap_after = gb(system_after.get("swap_used_bytes"))
    swap_delta = None
    if system_swap_before is not None and system_swap_after is not None:
        swap_delta = round(system_swap_after - system_swap_before, 2)
    return {
        "status": "completed",
        "error": None,
        "model": model,
        "provider": result.get("provider"),
        "backend": result.get("backend") or result.get("provider"),
        "quantization": result.get("quantization"),
        "quality": result.get("quality"),
        "resolution": result.get("resolution"),
        "width": result.get("width"),
        "height": result.get("height"),
        "duration": result.get("duration"),
        "fps": result.get("fps"),
        "frames": result.get("frames"),
        "runtime_start": "warm" if result.get("runtime_reused") is True else (
            "cold" if result.get("runtime_reused") is False else "unknown"
        ),
        "wall_seconds": wall,
        "provider_seconds": result.get("provider_elapsed_seconds"),
        "ram_before_gb": gb(before.get("ram_used_bytes")),
        "ram_peak_gb": gb(peak.get("ram_used_bytes")),
        "ram_after_gb": gb(after.get("ram_used_bytes")),
        "swap_before_gb": system_swap_before,
        "swap_peak_gb": gb(peak.get("swap_used_bytes")),
        "swap_after_gb": system_swap_after,
        "swap_delta_gb": swap_delta,
        "system_before": system_before,
        "system_after": system_after,
        "thermal_trace": thermal_trace,
        "path": result.get("path"),
    }


def failed_result(model, exc):
    return {
        "status": "failed",
        "error": str(exc),
        "model": model,
        "provider": None,
        "backend": None,
        "runtime_start": "—",
        "wall_seconds": None,
        "provider_seconds": None,
        "ram_peak_gb": None,
        "swap_peak_gb": None,
        "swap_delta_gb": None,
        "thermal_trace": None,
    }


def _thermal_summary(item):
    before = (item.get("system_before") or {}).get("thermal") or {}
    after = (item.get("system_after") or {}).get("thermal") or {}
    before_limit = before.get("cpu_speed_limit")
    after_limit = after.get("cpu_speed_limit")
    if before_limit is None and after_limit is None:
        return "—"
    return f"{before_limit if before_limit is not None else '?'}→{after_limit if after_limit is not None else '?'}%"


def print_table(results):
    print("\nErgebnisse")
    print("=" * 184)
    header = (
        f"{'Model':28} {'Status':9} {'Backend':15} {'Start':6} {'Size':13} "
        f"{'Wall':>9} {'Provider':>9} {'RAM peak':>10} {'Swap peak':>10} "
        f"{'Swap Δ':>9} {'CPU lim':>10} {'Thermal':>9} {'T-Samples':>18}"
    )
    print(header)
    print("-" * 184)
    for item in results:
        size = f"{item.get('width') or '?'}x{item.get('height') or '?'}"
        provider = item.get("provider_seconds")
        provider_text = f"{provider:.1f}s" if isinstance(provider, (int, float)) else "—"
        wall = item.get("wall_seconds")
        wall_text = f"{wall:.1f}s" if isinstance(wall, (int, float)) else "—"
        ram = item.get("ram_peak_gb")
        swap = item.get("swap_peak_gb")
        swap_delta = item.get("swap_delta_gb")
        swap_delta_text = f"{swap_delta:+.1f} GB" if isinstance(swap_delta, (int, float)) else "—"
        print(
            f"{item['model'][:28]:28} {item.get('status', '—')[:9]:9} "
            f"{str(item.get('backend') or '—')[:15]:15} {str(item.get('runtime_start') or '—')[:6]:6} "
            f"{size:13} {wall_text:>9} {provider_text:>9} "
            f"{(f'{ram:.1f} GB' if ram is not None else '—'):>10} "
            f"{(f'{swap:.1f} GB' if swap is not None else '—'):>10} "
            f"{swap_delta_text:>9} {_thermal_summary(item):>10} "
            f"{_thermal_flow(item.get('thermal_trace')):>9} "
            f"{_thermal_trace_compact(item.get('thermal_trace')):>18}"
        )
        if item.get("error"):
            print(f"  ↳ {str(item['error'])[:118]}")
    print("=" * 184)
    print("CPU lim = pmset CPU_Speed_Limit vor→nach dem Lauf; kein Temperaturwert.")
    print("Thermal = powermetrics Start→Peak→Ende; N=Nominal, M=Moderate, H=Heavy, T=Trapping.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8060")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--quality", choices=("preview", "fast", "standard", "quality"), default="standard")
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--fps", type=int, choices=(8, 24), default=24)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--aspect-ratio", choices=("16:9", "9:16"), default="16:9")
    parser.add_argument("--prompt", default="Cinematic tracking shot of a red sports car driving through rain at night, realistic reflections, smooth motion")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--cold-warm-cold",
        action="store_true",
        help="run exactly cold -> warm -> forced-cold for one native-MLX model",
    )
    parser.add_argument(
        "--thermal",
        action="store_true",
        help="sample macOS powermetrics thermal pressure once per second during each run",
    )
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    models = request_json("GET", base_url + "/models", timeout=15)
    available = {item["id"]: item for item in models.get("models", [])}
    missing = [model for model in args.models if model not in available]
    if missing:
        raise RuntimeError("Unbekannte Video-Modelle: " + ", ".join(missing))

    if args.thermal:
        _prepare_thermal_sampling()

    if args.cold_warm_cold:
        if len(args.models) != 1:
            raise RuntimeError("--cold-warm-cold benötigt genau ein Modell")
        model = args.models[0]
        if available[model].get("provider") != "ltx-mlx":
            raise RuntimeError("--cold-warm-cold ist nur für das native MLX-Backend verfügbar")
        reset = reset_mlx_runtime(base_url)
        print(
            "\nIsolation Cold → Warm → Cold: "
            f"MLX-Worker zurückgesetzt (vorher geladen: {'ja' if reset.get('was_loaded') else 'nein'}).",
            flush=True,
        )
        repeat_count = 3
    else:
        repeat_count = max(1, args.repeats)

    results = []
    for repeat in range(1, repeat_count + 1):
        for model in args.models:
            print(f"\n[{repeat}/{repeat_count}] {model}", flush=True)
            if not available[model].get("available"):
                reason = available[model].get("availability_note") or "Backend nicht verfügbar"
                print(f"  FAILED: {reason}", file=sys.stderr)
                results.append(failed_result(model, reason))
                continue
            try:
                results.append(run_job(base_url, model, args, repeat))
            except Exception as exc:
                print(f"  FAILED: {exc}", file=sys.stderr)
                results.append(failed_result(model, exc))

        if args.cold_warm_cold and repeat == 2:
            reset = reset_mlx_runtime(base_url)
            print(
                "\n  MLX-Worker nach Warm-Lauf gezielt zurückgesetzt "
                f"(vorher geladen: {'ja' if reset.get('was_loaded') else 'nein'}).",
                flush=True,
            )

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_table(results)

    if not any(item.get("status") == "completed" for item in results):
        raise RuntimeError("Kein Benchmark-Backend konnte einen Lauf abschließen")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
