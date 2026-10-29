#!/usr/bin/env python3
"""Paired CPU/file-I/O benchmark; no live process inspection, signals or models."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import managed_process


def previous_remaining(record, table):
    """Reference implementation from the audit base a71f595, kept only here."""
    return [value for value in table.values() if not value["zombie"] and (
        value["pgid"] == record["pid"] or any(
            managed_process.identities.same(saved, value) for saved in managed_process._members(record)))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--rows", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.samples <= 100 or not 5 <= args.rows <= 10000:
        parser.error("samples: 1–100; rows: 5–10000")
    before, after = [], []
    old_root = managed_process.gate.ROOT
    with tempfile.TemporaryDirectory(prefix="mlx-process-audit-") as directory:
        try:
            managed_process.gate.ROOT = Path(directory)
            root = Path(directory) / "processes"
            root.mkdir()
            record = {"pid": 987654, "token": "isolated-benchmark"}
            members = [{"pid": pid, "birth": str(pid)} for pid in range(100001, 100006)]
            (root / "987654.members.json").write_text(json.dumps({"token": record["token"], "members": members}))
            table = {pid: {"pid": pid, "pgid": pid + 1000000, "birth": str(pid), "zombie": False}
                     for pid in range(100001, 100001 + args.rows)}
            for sample in range(args.samples + 1):
                # Alternate order to reduce warm-cache/order bias.
                pairs = [(previous_remaining, before), (managed_process.remaining, after)]
                for function, timings in pairs if sample % 2 else reversed(pairs):
                    started = time.perf_counter_ns()
                    result = function(record, table)
                    elapsed = (time.perf_counter_ns() - started) / 1e6
                    assert [item["pid"] for item in result] == [item["pid"] for item in members]
                    if sample:
                        timings.append(elapsed)
        finally:
            managed_process.gate.ROOT = old_root
    print(json.dumps({"scenario": "synthetic process rows with actual temporary JSON reads; no live services",
                      "samples": args.samples, "warmup_pairs": 1, "rows": args.rows,
                      "before_median_ms": statistics.median(before), "after_median_ms": statistics.median(after),
                      "before_min_ms": min(before), "before_max_ms": max(before),
                      "after_min_ms": min(after), "after_max_ms": max(after),
                      "member_file_reads_per_scan_before": args.rows, "member_file_reads_per_scan_after": 1}, indent=2))


if __name__ == "__main__":
    main()
