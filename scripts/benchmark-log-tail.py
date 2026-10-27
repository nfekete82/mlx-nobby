#!/usr/bin/env python3
"""Compare bounded log tails to the previous full-file reader on synthetic data."""

import argparse
import gc
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.log_tail import read_log_tail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mib", type=int, default=64, choices=range(1, 257), metavar="1..256")
    parser.add_argument("--trials", type=int, default=5, choices=range(1, 11), metavar="1..10")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="mlx-log-benchmark-") as directory:
        path = Path(directory) / "synthetic.log"
        block = (b"synthetic log entry " + b"x" * 235 + b"\n") * 4096
        with path.open("wb") as handle:
            for _ in range(args.mib):
                handle.write(block)

        def original():
            content = path.read_text(encoding="utf-8", errors="replace")
            return content.replace("\x00", "").splitlines()[-400:]

        def bounded():
            return read_log_tail(path, 400, strip_nulls=True)

        assert original() == bounded()
        readers = {"original": original, "bounded": bounded}
        times = {key: [] for key in readers}
        for trial in range(args.trials):
            for key in (list(readers) if trial % 2 == 0 else list(reversed(readers))):
                started = time.perf_counter()
                readers[key]()
                times[key].append((time.perf_counter() - started) * 1000)

        results = {}
        for key, reader in readers.items():
            gc.collect()
            tracemalloc.start()
            reader()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            results[key] = {
                "median_ms": round(statistics.median(times[key]), 3),
                "trials_ms": [round(value, 3) for value in times[key]],
                "python_peak_mib": round(peak / 1024**2, 3),
            }
        print(json.dumps({
            "synthetic_bytes": path.stat().st_size, "lines_requested": 400,
            "trials": args.trials, "warm_file_cache": True,
            "memory_measured_separately": True, "results": results,
        }, indent=2))


if __name__ == "__main__":
    main()
