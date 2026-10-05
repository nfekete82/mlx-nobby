#!/usr/bin/env python3
"""Record and inspect persistent local model evaluations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import model_evaluations


def metric_value(value: str):
    lowered = value.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def parse_metrics(values: list[str] | None) -> dict:
    metrics = {}
    for item in values or []:
        if "=" not in item:
            raise ValueError(f"metric must use key=value: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("metric key must not be empty")
        metrics[key] = metric_value(value.strip())
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record", help="Record one evaluation")
    record_parser.add_argument("--model", required=True)
    record_parser.add_argument("--kind", required=True, choices=sorted(model_evaluations.VALID_KINDS))
    record_parser.add_argument("--status", required=True, choices=sorted(model_evaluations.VALID_STATUSES))
    record_parser.add_argument("--reason", required=True)
    record_parser.add_argument("--compared-to")
    record_parser.add_argument("--source", default="manual")
    record_parser.add_argument("--metric", action="append", help="Scalar key=value metric; repeat as needed")

    list_parser = subparsers.add_parser("list", help="List latest decision per model and kind")
    list_parser.add_argument("--kind", choices=sorted(model_evaluations.VALID_KINDS))
    list_parser.add_argument("--status", choices=sorted(model_evaluations.VALID_STATUSES))
    list_parser.add_argument("--json", action="store_true")

    show_parser = subparsers.add_parser("show", help="Show latest evaluation for one model")
    show_parser.add_argument("--model", required=True)
    show_parser.add_argument("--kind", choices=sorted(model_evaluations.VALID_KINDS))

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "record":
            evaluation = model_evaluations.record(
                args.model,
                kind=args.kind,
                status=args.status,
                reason=args.reason,
                compared_to=args.compared_to,
                metrics=parse_metrics(args.metric),
                source=args.source,
            )
            print(json.dumps(evaluation, ensure_ascii=False, indent=2))
            return 0

        if args.command == "show":
            evaluation = model_evaluations.latest(args.model, kind=args.kind)
            if evaluation is None:
                print("No evaluation found.", file=sys.stderr)
                return 1
            print(json.dumps(evaluation, ensure_ascii=False, indent=2))
            return 0

        evaluations = model_evaluations.list_latest(kind=args.kind, status=args.status)
        if args.json:
            print(json.dumps({"evaluations": evaluations}, ensure_ascii=False, indent=2))
            return 0
        if not evaluations:
            print("No model evaluations recorded.")
            return 0
        for evaluation in evaluations:
            compared = f" vs {evaluation['compared_to']}" if evaluation.get("compared_to") else ""
            print(
                f"{evaluation['status']:10} {evaluation['kind']:12} "
                f"{evaluation['model']}{compared}\n"
                f"  {evaluation['reason']}"
            )
        return 0
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
