#!/usr/bin/env python3
"""Benchmark the current Whisper STT model against Qwen3-ASR locally.

The parent process has no MLX dependency. Each candidate runs in a fresh speech
virtual-environment process, loads exactly once, then transcribes all requested
audio files for the requested number of runs. Optional same-stem .txt files are
used as reference transcripts for word error rate (WER).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import model_evaluations


DEFAULT_MODELS = (
    "mlx-community/whisper-large-v3-turbo-asr-fp16",
    "mlx-community/Qwen3-ASR-1.7B-6bit",
)


def normalize_words(text: str) -> list[str]:
    return re.findall(r"[\wäöüß]+", str(text or "").casefold(), flags=re.UNICODE)


def word_error_rate(reference: str, hypothesis: str) -> float | None:
    expected = normalize_words(reference)
    actual = normalize_words(hypothesis)
    if not expected:
        return None

    previous = list(range(len(actual) + 1))
    for row, expected_word in enumerate(expected, start=1):
        current = [row]
        for column, actual_word in enumerate(actual, start=1):
            substitution = previous[column - 1] + (expected_word != actual_word)
            insertion = current[column - 1] + 1
            deletion = previous[column] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1] / len(expected)


def sidecar_reference(audio: Path) -> str | None:
    path = audio.with_suffix(".txt")
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _result_text(result) -> str:
    if isinstance(result, str):
        return result.strip()
    text = getattr(result, "text", None)
    if text is not None:
        return str(text).strip()
    if isinstance(result, dict):
        return str(result.get("text") or "").strip()
    return str(result).strip()


def worker(model_name: str, audio_files: list[Path], runs: int, output: Path) -> int:
    # Import only in the speech-venv worker. This keeps normal CLI/report tests
    # independent of Metal and mlx-audio.
    from mlx_audio.stt import load

    load_started = time.perf_counter()
    model = load(model_name)
    load_seconds = time.perf_counter() - load_started
    rows = []

    for audio in audio_files:
        for run in range(runs):
            started = time.perf_counter()
            result = model.generate(str(audio))
            elapsed = time.perf_counter() - started
            rows.append(
                {
                    "audio": str(audio),
                    "run": run + 1,
                    "seconds": elapsed,
                    "text": _result_text(result),
                }
            )

    output.write_text(
        json.dumps(
            {
                "model": model_name,
                "load_seconds": load_seconds,
                "runs": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def summarize_model(payload: dict, references: dict[str, str]) -> dict:
    rows = list(payload.get("runs") or [])
    seconds = [float(row["seconds"]) for row in rows if row.get("seconds") is not None]
    wers = []
    for row in rows:
        reference = references.get(str(row.get("audio") or ""))
        if reference is None:
            continue
        score = word_error_rate(reference, str(row.get("text") or ""))
        if score is not None:
            wers.append(score)

    summary = {
        "model": payload.get("model"),
        "load_seconds": float(payload.get("load_seconds") or 0.0),
        "transcriptions": len(rows),
        "median_seconds": statistics.median(seconds) if seconds else None,
        "mean_seconds": statistics.fmean(seconds) if seconds else None,
        "median_wer": statistics.median(wers) if wers else None,
        "mean_wer": statistics.fmean(wers) if wers else None,
    }
    return summary


def recommendation(summaries: list[dict]) -> dict:
    usable = [item for item in summaries if item.get("median_seconds") is not None]
    if not usable:
        return {"winner": None, "reason": "no successful measurements"}

    quality = [item for item in usable if item.get("median_wer") is not None]
    if quality:
        winner = min(
            quality,
            key=lambda item: (item["median_wer"], item["median_seconds"]),
        )
        return {
            "winner": winner["model"],
            "reason": "lowest median WER, then lowest median inference time",
        }

    winner = min(usable, key=lambda item: item["median_seconds"])
    return {
        "winner": winner["model"],
        "reason": "lowest median inference time; add .txt sidecars to compare accuracy",
    }


def evaluation_metrics(summary: dict) -> dict:
    return {
        key: summary.get(key)
        for key in (
            "load_seconds",
            "transcriptions",
            "median_seconds",
            "mean_seconds",
            "median_wer",
            "mean_wer",
        )
    }


def record_asr_evaluations(summaries: list[dict], decision: dict) -> list[dict]:
    winner_name = str(decision.get("winner") or "").strip()
    if not winner_name:
        return []
    winner = next(
        (item for item in summaries if str(item.get("model") or "") == winner_name),
        None,
    )
    if winner is None:
        return []

    evaluations = []
    alternatives = [
        str(item.get("model") or "")
        for item in summaries
        if str(item.get("model") or "") and str(item.get("model") or "") != winner_name
    ]
    for summary in summaries:
        model = str(summary.get("model") or "").strip()
        if not model:
            continue
        is_winner = model == winner_name
        compared_to = (alternatives[0] if is_winner and len(alternatives) == 1 else winner_name if not is_winner else None)
        if is_winner:
            status = "keep"
            reason = f"ASR benchmark winner: {decision.get('reason') or 'best local result'}."
        else:
            status = "rejected"
            reason = (
                f"Did not beat {winner_name} in the local ASR benchmark: "
                f"{decision.get('reason') or 'winner selected by benchmark policy'}."
            )
        evaluations.append(
            model_evaluations.record(
                model,
                kind="asr",
                status=status,
                reason=reason,
                compared_to=compared_to,
                metrics=evaluation_metrics(summary),
                source="benchmark-asr-v1",
            )
        )
    return evaluations


def parent(args) -> int:
    audio_files = [Path(value).expanduser().resolve() for value in args.audio]
    missing = [str(path) for path in audio_files if not path.is_file()]
    if missing:
        raise SystemExit("Missing audio file(s): " + ", ".join(missing))

    speech_python = Path(args.speech_python).expanduser().resolve()
    if not speech_python.is_file():
        raise SystemExit(f"Speech Python is missing: {speech_python}")

    references = {
        str(audio): reference
        for audio in audio_files
        if (reference := sidecar_reference(audio)) is not None
    }
    model_results = []

    with tempfile.TemporaryDirectory(prefix="mlx-nobby-asr-") as temporary:
        temporary_dir = Path(temporary)
        for index, model in enumerate(args.models):
            worker_output = temporary_dir / f"model-{index}.json"
            command = [
                str(speech_python),
                str(Path(__file__).resolve()),
                "--worker",
                "--model",
                model,
                "--runs",
                str(args.runs),
                "--worker-output",
                str(worker_output),
            ]
            for audio in audio_files:
                command.extend(["--audio", str(audio)])

            print(f"[ASR] Benchmarking {model}", flush=True)
            completed = subprocess.run(command, text=True, capture_output=True)
            if completed.returncode != 0 or not worker_output.is_file():
                model_results.append(
                    {
                        "model": model,
                        "error": (completed.stderr or completed.stdout or "worker failed").strip(),
                    }
                )
                continue
            model_results.append(json.loads(worker_output.read_text(encoding="utf-8")))

    summaries = [
        summarize_model(item, references)
        for item in model_results
        if not item.get("error")
    ]
    decision = recommendation(summaries)
    report = {
        "audio": [str(path) for path in audio_files],
        "runs_per_audio": args.runs,
        "references": sorted(references),
        "models": model_results,
        "summary": summaries,
        "recommendation": decision,
    }
    if not args.no_record_evaluations:
        try:
            report["evaluations"] = record_asr_evaluations(summaries, decision)
        except Exception as exc:
            # Benchmark output remains useful even when local decision storage is unavailable.
            report["evaluation_error"] = str(exc)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "summary": summaries,
                "recommendation": report["recommendation"],
                "evaluations": report.get("evaluations", []),
                "evaluation_error": report.get("evaluation_error"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if len(summaries) == len(args.models) else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", action="append", required=True, help="Audio file; repeat for multiple samples")
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument(
        "--speech-python",
        default=str(Path(__file__).resolve().parents[1] / "speech-venv/bin/python"),
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/asr-benchmark.json"))
    parser.add_argument(
        "--no-record-evaluations",
        action="store_true",
        help="Do not persist winner/loser decisions in ~/.config/mlx-web/model-evaluations.json",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--model", help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.worker and (not args.model or args.worker_output is None):
        parser.error("worker mode requires --model and --worker-output")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.worker:
        return worker(
            args.model,
            [Path(value).expanduser().resolve() for value in args.audio],
            args.runs,
            args.worker_output,
        )
    return parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
