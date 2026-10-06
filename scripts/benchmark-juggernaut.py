#!/usr/bin/env python3
"""A/B benchmark Juggernaut XI v11 SDXL schedulers on Apple Silicon."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_DIR = Path.home() / "Models/JuggernautXL"
DEFAULT_OUTPUT_DIR = Path.home() / ".config/mlx-web/benchmarks/juggernaut"
DEFAULT_SCHEDULERS = (
    "dpmpp-2m-karras",
    "dpmpp-2m-sde-karras",
)
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
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def elapsed_text(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def resolve_model_files(model_dir):
    model_dir = Path(model_dir).expanduser().resolve()
    checkpoints = sorted(model_dir.glob("*.safetensors"))
    if len(checkpoints) != 1:
        raise RuntimeError(
            f"Erwartet genau einen Juggernaut-Checkpoint unter {model_dir}; "
            f"gefunden: {len(checkpoints)}"
        )
    config = model_dir / "config"
    if not (config / "model_index.json").is_file():
        raise RuntimeError(
            f"Diffusers-Konfiguration fehlt: {config / 'model_index.json'}"
        )
    return checkpoints[0], config


def resolve_image_python():
    candidate = PROJECT_DIR / "image-venv/bin/python"
    if not candidate.is_file():
        raise RuntimeError(
            f"Image-Python fehlt: {candidate}. Bitte MLX Nobby Images installieren."
        )
    return candidate


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


def _thermal_text(trace):
    if not trace or not trace.get("samples"):
        return "—"
    counts = trace.get("counts") or {}
    compact = "/".join(
        f"{short}{counts[level]}"
        for level, short in (
            ("Nominal", "N"),
            ("Moderate", "M"),
            ("Heavy", "H"),
            ("Trapping", "T"),
        )
        if counts.get(level)
    )
    return (
        f"{trace.get('first') or '?'}→{trace.get('peak') or '?'}→"
        f"{trace.get('last') or '?'} {compact}"
    )


def prepare_thermal_sampling():
    if sys.platform != "darwin":
        raise RuntimeError("--thermal benötigt macOS")
    if not Path("/usr/bin/powermetrics").is_file():
        raise RuntimeError("/usr/bin/powermetrics wurde nicht gefunden")
    print(
        "Thermal-Telemetrie: sudo wird einmal vorbereitet; "
        "powermetrics läuft pro A/B-Lauf.",
        flush=True,
    )
    completed = subprocess.run(["sudo", "-v"], check=False)
    if completed.returncode != 0:
        raise RuntimeError("sudo-Freigabe für powermetrics fehlgeschlagen")


def start_thermal_sampler(enabled):
    if not enabled:
        return None
    log = tempfile.NamedTemporaryFile(
        mode="w+",
        encoding="utf-8",
        prefix="mlx-nobby-juggernaut-thermal-",
        suffix=".log",
        delete=False,
    )
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
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return {"process": process, "log": log, "path": log.name}


def stop_thermal_sampler(state):
    if not state:
        return None
    process = state["process"]
    log = state["log"]
    path = state["path"]
    try:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
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
    return _parse_powermetrics_thermal(output)


class Worker:
    def __init__(self, python, checkpoint, config):
        self.checkpoint = Path(checkpoint)
        self.config = Path(config)
        self.diagnostics = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            [str(python), str(PROJECT_DIR / "sdxl_worker.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.diagnostics,
            text=True,
            bufsize=1,
            env={
                **os.environ,
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "TOKENIZERS_PARALLELISM": "false",
            },
            start_new_session=True,
        )

    def failure_text(self):
        self.diagnostics.flush()
        self.diagnostics.seek(0, 2)
        size = self.diagnostics.tell()
        self.diagnostics.seek(max(0, size - 10000))
        return self.diagnostics.read().decode("utf-8", errors="replace").strip()

    def run(self, params, output, timeout, *, show_progress=True):
        if self.process.poll() is not None:
            raise RuntimeError(
                self.failure_text()
                or f"SDXL worker beendet (Exit {self.process.returncode})"
            )
        request_id = secrets.token_hex(12)
        request = {
            "request_id": request_id,
            "checkpoint": str(self.checkpoint),
            "config": str(self.config),
            "params": params,
            "output": str(output),
        }
        started = time.monotonic()
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        deadline = started + timeout
        last_step = None
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        self.failure_text()
                        or f"SDXL worker beendet (Exit {self.process.returncode})"
                    )
                events = selector.select(0.5)
                if not events:
                    continue
                line = self.process.stdout.readline()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("request_id") != request_id:
                    continue
                if event.get("type") == "runtime":
                    step = event.get("step")
                    total = event.get("total_steps")
                    if show_progress and step != last_step:
                        print(
                            f"    {step}/{total} · {elapsed_text(time.monotonic() - started)}",
                            flush=True,
                        )
                        last_step = step
                elif event.get("type") == "error":
                    raise RuntimeError(
                        f"{event.get('error_type')}: {event.get('message')}"
                    )
                elif event.get("type") == "complete":
                    wall = time.monotonic() - started
                    if not Path(output).is_file():
                        raise RuntimeError("Worker meldete complete, aber PNG fehlt")
                    return wall, event
        raise RuntimeError(f"Timeout nach {timeout:.0f} s")

    def close(self):
        try:
            if self.process.poll() is None:
                if os.name == "posix":
                    os.killpg(self.process.pid, signal.SIGTERM)
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(self.process.pid, signal.SIGKILL)
                    else:
                        self.process.kill()
                    self.process.wait(timeout=2)
        finally:
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            self.diagnostics.close()


def build_params(args, scheduler, *, warmup=False):
    return {
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt or None,
        "width": 512 if warmup else args.width,
        "height": 512 if warmup else args.height,
        "steps": args.warmup_steps if warmup else args.steps,
        "guidance": args.guidance,
        "seed": args.seed,
        "scheduler": scheduler,
    }


def print_results(results):
    print()
    print("Ergebnisse")
    print("=" * 112)
    print(
        f"{'Scheduler':26} {'Run':>4} {'Size':>11} {'Steps':>5} "
        f"{'CFG':>5} {'Wall':>9} {'Thermal':30} Bild"
    )
    print("-" * 112)
    for item in results:
        print(
            f"{item['scheduler'][:26]:26} {item['run']:>4} "
            f"{item['width']}x{item['height']: <5} {item['steps']:>5} "
            f"{item['guidance']:>5.1f} {item['wall_seconds']:>8.1f}s "
            f"{_thermal_text(item.get('thermal'))[:30]:30} {item['path']}"
        )
    print("=" * 112)
    print("A/B-Bilder verwenden denselben Prompt, Seed, Steps, CFG und dieselbe Auflösung.")
    print("Der Warmup lädt nur das Modell; seine Laufzeit wird nicht gewertet.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-url", default="http://127.0.0.1:8030")
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--schedulers", nargs="+", default=list(DEFAULT_SCHEDULERS))
    parser.add_argument("--width", type=int, default=832)
    parser.add_argument("--height", type=int, default=1216)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--guidance", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--warmup-steps", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--thermal", action="store_true")
    parser.add_argument("--skip-service-unload", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--prompt",
        default=(
            "Photorealistic editorial portrait of a woman in her thirties, "
            "natural skin texture, detailed eyes, soft window light, "
            "85mm lens, shallow depth of field, neutral studio background"
        ),
    )
    parser.add_argument("--negative-prompt", default="")
    args = parser.parse_args()

    if args.width % 16 or args.height % 16:
        raise RuntimeError("width und height müssen durch 16 teilbar sein")
    if args.width > 1216 or args.height > 1216:
        raise RuntimeError("Juggernaut/SDXL unterstützt hier maximal 1216 Pixel pro Kante")
    if not 1 <= args.steps <= 50:
        raise RuntimeError("--steps muss zwischen 1 und 50 liegen")
    if not 1 <= args.warmup_steps <= 4:
        raise RuntimeError("--warmup-steps muss zwischen 1 und 4 liegen")
    if not 0 <= args.guidance <= 10:
        raise RuntimeError("--guidance muss zwischen 0 und 10 liegen")
    if args.repeats < 1:
        raise RuntimeError("--repeats muss mindestens 1 sein")

    checkpoint, config = resolve_model_files(args.model_dir)
    image_python = resolve_image_python()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.thermal:
        prepare_thermal_sampling()

    if not args.skip_service_unload:
        print("Image-Service: vorhandenen SDXL-Worker entladen …", flush=True)
        request_json(
            "POST",
            args.image_url.rstrip("/") + "/unload",
            timeout=60,
        )

    print(f"Checkpoint: {checkpoint.name}", flush=True)
    print(f"A/B: {', '.join(args.schedulers)}", flush=True)
    print(
        f"Canvas: {args.width}x{args.height} · {args.steps} Steps · "
        f"CFG {args.guidance:g} · Seed {args.seed}",
        flush=True,
    )

    worker = Worker(image_python, checkpoint, config)
    results = []
    warmup_path = output_dir / ".juggernaut-warmup.png"
    try:
        print()
        print("Warmup: Modell laden …", flush=True)
        warmup_wall, _ = worker.run(
            build_params(args, args.schedulers[0], warmup=True),
            warmup_path,
            args.timeout,
            show_progress=False,
        )
        warmup_path.unlink(missing_ok=True)
        print(f"Warmup fertig · {warmup_wall:.1f}s", flush=True)

        total = len(args.schedulers) * args.repeats
        index = 0
        for repeat in range(1, args.repeats + 1):
            for scheduler in args.schedulers:
                index += 1
                safe_scheduler = re.sub(r"[^a-z0-9-]+", "-", scheduler.lower()).strip("-")
                output = output_dir / (
                    f"juggernaut-xi-{safe_scheduler}-"
                    f"seed{args.seed}-r{repeat}.png"
                )
                print()
                print(f"[{index}/{total}] {scheduler}", flush=True)
                thermal_state = start_thermal_sampler(args.thermal)
                thermal = None
                try:
                    wall, complete = worker.run(
                        build_params(args, scheduler),
                        output,
                        args.timeout,
                    )
                finally:
                    thermal = stop_thermal_sampler(thermal_state)
                print(
                    f"    fertig · {wall:.1f}s · Thermal {_thermal_text(thermal)}",
                    flush=True,
                )
                results.append({
                    "scheduler": complete.get("scheduler") or scheduler,
                    "run": repeat,
                    "width": args.width,
                    "height": args.height,
                    "steps": args.steps,
                    "guidance": args.guidance,
                    "seed": args.seed,
                    "wall_seconds": round(wall, 3),
                    "thermal": thermal,
                    "path": str(output),
                })
    finally:
        warmup_path.unlink(missing_ok=True)
        worker.close()

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_results(results)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("Abgebrochen.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
