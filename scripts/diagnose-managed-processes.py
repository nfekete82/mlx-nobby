#!/usr/bin/env python3
"""Inspect owned process state without printing arguments, prompts or media."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_lifecycle_gate as gate
import managed_process
import process_identity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup-stale", action="store_true", help="Remove only verified empty records; never send signals")
    args = parser.parse_args()
    table = process_identity.table()
    records = []
    for path in (gate.ROOT / "processes").glob("*.json"):
        if not path.stem.isdigit():
            continue
        record = json.loads(path.read_text())
        remaining = managed_process.remaining(record, table)
        records.append({"pid": record["pid"], "pgid": record["pid"], "owner": record.get("owner"),
                        "leader_alive": record["pid"] in table and not table[record["pid"]]["zombie"],
                        "remaining": [{k: item[k] for k in ("pid", "pgid", "zombie")} for item in remaining]})
    print(json.dumps({"gate_blocked": gate.blocked(), "records": records,
                      "removed_empty_records": managed_process.prune_stale() if args.cleanup_stale else []}, indent=2))


if __name__ == "__main__":
    main()
