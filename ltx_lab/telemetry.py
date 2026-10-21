"""CPU-only system sampling and synchronized, nested phase measurements."""
from __future__ import annotations

import contextlib
import json
import math
import os
import re
import resource
import subprocess
import threading
import time
from pathlib import Path


def command(args):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=5)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_vm_stat(text):
    match = re.search(r"page size of (\d+) bytes", text)
    if not match:
        return {}
    size = int(match[1])
    pages = {k: int(v) for k, v in re.findall(r"^([^:]+):\s+(\d+)\.", text, re.M)}
    used = sum(pages.get(k, 0) for k in ("Pages active", "Pages inactive", "Pages wired down",
                                        "Pages occupied by compressor", "Pages speculative"))
    available = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative"))
    return {"ram_used_bytes": used * size, "available_estimate_bytes": available * size,
            "compressor_bytes": pages.get("Pages occupied by compressor", 0) * size,
            "pageins": pages.get("Pageins"), "pageouts": pages.get("Pageouts")}


def system_snapshot():
    vm = parse_vm_stat(command(["/usr/bin/vm_stat"]))
    swap = command(["/usr/sbin/sysctl", "-n", "vm.swapusage"])
    match = re.search(r"used\s*=\s*([\d.]+)([KMGT])", swap)
    pressure = command(["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"])
    vm.update({"timestamp": time.time(), "swap_used_bytes": (
        int(float(match[1]) * 1024 ** ("KMGT".index(match[2]) + 1)) if match else None),
        "memory_pressure_level": int(pressure) if pressure.isdigit() else None,
        "rss_bytes": None})
    # No MLX calls on the sampler thread; Metal APIs stay on the generation thread.
    rss = command(["/bin/ps", "-o", "rss=", "-p", str(os.getpid())])
    if rss.isdigit():
        vm["rss_bytes"] = int(rss) * 1024
    return vm


def preflight(min_available_gib=20):
    if not math.isfinite(min_available_gib) or min_available_gib < 16:
        raise ValueError("At least 16 GiB estimated availability required for lab admission")
    snapshot = system_snapshot()
    processes = command(["/bin/ps", "-axo", "pid=,comm="])
    # Fail closed if process visibility is unavailable. Do not stop any process.
    competing = [line.strip() for line in processes.splitlines()
                 if any(name in line for name in ("video_mlx_worker", "ltx2_server", "mlx_vlm"))]
    # comm often contains only 'python': use arguments for matching, emit PIDs only.
    args = command(["/bin/ps", "-axo", "pid=,args="])
    for line in args.splitlines():
        if any(name in line for name in (" -m mlx_vlm ", "video_mlx_worker.py", "ltx2_server.py",
                                         "ltx-talking-photo-a2v.py", " -m ltx_lab.runner ")):
            if line.strip().split()[0] != str(os.getpid()):
                competing.append(line.strip().split()[0])
    reasons = []
    if not processes or not args:
        reasons.append("Process visibility unavailable")
    if competing:
        reasons.append("Competing LTX/VLM process present; services will not be stopped")
    if snapshot.get("memory_pressure_level") != 1:
        reasons.append("Memory pressure not confirmed normal")
    if snapshot.get("available_estimate_bytes", 0) < min_available_gib * 1024**3:
        reasons.append(f"Less than {min_available_gib:g} GiB estimated available memory")
    if snapshot.get("swap_used_bytes") is None:
        reasons.append("Swap telemetry unavailable")
    return {"allowed": not reasons, "reasons": reasons, "snapshot": snapshot,
            "competing_process_count": len(set(competing)), "min_available_gib": min_available_gib,
            "note": "Admission is a snapshot, not a memory guarantee; no service controls invoked"}


class MemorySampler:
    def __init__(self, snapshot=system_snapshot, interval=0.5):
        self.snapshot, self.interval = snapshot, interval
        self.samples = []
        self.stop_event = threading.Event()

    def _sample(self):
        self.samples.append(self.snapshot())

    def _run(self):
        while not self.stop_event.wait(self.interval):
            self._sample()

    def __enter__(self):
        self._sample()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop_event.set()
        self.thread.join(timeout=20)
        self._sample()

    def summary(self):
        def peak(key):
            values = [s[key] for s in self.samples if isinstance(s.get(key), (int, float))]
            return max(values) if values else None
        before, after = self.samples[0], self.samples[-1]
        swap = peak("swap_used_bytes")
        return {"before": before, "after": after,
                "peak_system_ram_bytes": peak("ram_used_bytes"), "peak_rss_bytes": peak("rss_bytes"),
                "peak_swap_bytes": swap,
                "swap_growth_bytes": (max(0, swap - before["swap_used_bytes"])
                                      if swap is not None and before.get("swap_used_bytes") is not None else None),
                "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "sample_count": len(self.samples), "sample_interval_seconds": self.interval,
                "units": "bytes; ru_maxrss is bytes on macOS; system RAM is not process memory"}

    def check(self):
        """Abort at the next Python phase/step boundary; never control other services."""
        if not self.samples:
            return
        latest, first = self.samples[-1], self.samples[0]
        if latest.get("memory_pressure_level") == 4:
            raise RuntimeError("Lab safety stop: critical system memory pressure")
        before, current = first.get("swap_used_bytes"), latest.get("swap_used_bytes")
        if before is not None and current is not None and current - before > 256 * 1024**2:
            raise RuntimeError("Lab safety stop: sampled swap growth exceeds 256 MiB")


class Recorder:
    """Inclusive and exclusive wall times; sync cost recorded, never hidden as GPU time."""
    def __init__(self, mx, clock=time.perf_counter):
        self.mx, self.clock = mx, clock
        self.events, self.stack, self.steps = [], [], []
        self.effective = {"dit_compute": [], "sparse_attention_calls": 0}
        self.zero = clock()
        self.unix_origin = time.time()
        self.guard = lambda: None

    def materialize(self, value):
        arrays = []
        def visit(item):
            if isinstance(item, self.mx.array):
                arrays.append(item)
            elif isinstance(item, dict):
                for v in item.values():
                    visit(v)
            elif isinstance(item, (tuple, list)):
                for v in item:
                    visit(v)
            elif hasattr(item, "__dataclass_fields__"):
                for name in item.__dataclass_fields__:
                    visit(getattr(item, name))
        visit(value)
        if arrays:
            self.mx.eval(*arrays)

    def metal(self):
        return {"active_bytes": self.mx.get_active_memory(), "cache_bytes": self.mx.get_cache_memory(),
                "peak_since_run_reset_bytes": self.mx.get_peak_memory()}

    @contextlib.contextmanager
    def span(self, phase, **detail):
        self.guard()
        sync_start = self.clock()
        self.mx.synchronize()
        start = self.clock()
        event = {"phase": phase, "start_seconds": start - self.zero,
                 "entry_sync_seconds": start - sync_start, "detail": detail,
                 "parent": self.stack[-1]["phase"] if self.stack else None,
                 "children_seconds": 0.0, "metal_before": self.metal(), "status": "running"}
        self.stack.append(event)
        try:
            yield event
            event["status"] = "completed"
        except BaseException:
            event["status"] = "failed"
            raise
        finally:
            try:
                self.mx.synchronize()
            finally:
                event["seconds"] = self.clock() - start
                event["self_seconds"] = max(0.0, event["seconds"] - event.pop("children_seconds"))
                event["metal_after"] = self.metal()
                self.stack.pop()
                if self.stack:
                    self.stack[-1]["children_seconds"] += self.clock() - sync_start
                self.events.append(event)

    def report(self, samples=()):
        totals = {}
        for event in self.events:
            row = totals.setdefault(event["phase"], {"calls": 0, "inclusive_seconds": 0.0, "self_seconds": 0.0})
            row["calls"] += 1
            row["inclusive_seconds"] += event["seconds"]
            row["self_seconds"] += event["self_seconds"]
        for phase, row in totals.items():
            intervals = [(e["start_seconds"], e["start_seconds"] + e["seconds"])
                         for e in self.events if e["phase"] == phase]
            relevant = [sample for sample in samples if any(
                start <= sample["timestamp"] - self.unix_origin <= end for start, end in intervals)]
            for key in ("ram_used_bytes", "swap_used_bytes", "rss_bytes"):
                values = [sample[key] for sample in relevant if isinstance(sample.get(key), (int, float))]
                row[f"sampled_peak_{key}"] = max(values) if values else None
            row["memory_sample_count"] = len(relevant)
        return {"phases": totals, "events": self.events, "steps": self.steps, "effective": self.effective,
                "metal": self.metal(), "timing": "synchronized wall time, not hardware GPU counters",
                "unix_clock_origin": self.unix_origin,
                "peak_scope": "mx.reset_peak_memory once at run start; nested phases never reset",
                "overlap": "mux_session overlaps VAE/streaming; never sum inclusive phase times"}


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)
