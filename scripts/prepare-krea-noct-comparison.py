#!/usr/bin/env python3
"""Prepare a matched comparison. Never load models, submit jobs or edit registries."""
import argparse
import csv
import json
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[1] / "docs/benchmarks/krea-noct-vs-juggernaut.json"


def seed_value(value):
    number = int(value)
    if not 0 <= number < 2**32:
        raise ValueError("Seed muss zwischen 0 und 4294967295 liegen")
    return number


def build_plan(manifest, seeds=None):
    selected = list(manifest["seeds"] if seeds is None else seeds)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Mindestens einen eindeutigen Seed angeben")
    for value in selected:
        seed_value(value)
    settings = manifest["juggernaut"]
    # This tool intentionally cannot turn the blocked candidate into an API job.
    if manifest["noct"]["runnable_in_mlx_nobby"] or manifest["noct"]["registered_model_id"] is not None:
        raise ValueError("Noct-Freigabe erfordert einen neuen geprüften Vergleichsworkflow")
    runs = []
    for case in manifest["cases"]:
        for seed in selected:
            shared = {"case_id": case["id"], "prompt": case["prompt"], "seed": seed,
                      "width": manifest["width"], "height": manifest["height"],
                      "negative_prompt": manifest["negative_prompt"]}
            runs.append({**shared, "model": "juggernaut-xl", "status": "prepared_not_rendered",
                         "settings": settings,
                         "request": {"operation": "generate", "chat_id": "krea-noct-comparison", "chat_revision": 0,
                                     "payload": {key: value for key, value in {
                                         **shared, "model": settings["model_id"], "quality": settings["quality"],
                                         "steps": settings["steps"], "guidance": settings["guidance"],
                                         "auto_size": False,
                                     }.items() if key != "case_id"}}})
            runs.append({**shared, "model": "krea-noct-v4", "status": "blocked", "request": None,
                         "settings": manifest["noct"], "blocked_reason": manifest["noct"]["blocked_reason"]})
    return {"schema_version": 1, "status": manifest["status"], "runs": runs,
            "rating_dimensions": manifest["rating_dimensions"], "measurement_fields": manifest["measurement_fields"]}


def write_bundle(output, manifest, seeds=None):
    plan = build_plan(manifest, seeds)
    # Refuse the whole existing directory, including previous scores and renders.
    output.mkdir(parents=True, exist_ok=False)
    (output / "requests").mkdir()
    (output / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["case_id", "model", "status", "checkpoint", "seed", "width", "height", "steps", "guidance", "sampler", "schedule",
              *plan["rating_dimensions"], *plan["measurement_fields"]]
    with (output / "scorecard.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, run in enumerate(plan["runs"], 1):
            settings = run["settings"]
            row = {key: run[key] for key in ("case_id", "model", "status", "seed", "width", "height")}
            row.update({key: settings[key] for key in ("checkpoint", "steps", "guidance", "sampler", "schedule")})
            writer.writerow(row)
            if run["request"] is not None:
                # Filenames never incorporate prompt text or untrusted path fragments.
                path = output / "requests" / f"{index:03d}-juggernaut-seed-{run['seed']}.json"
                path.write_text(json.dumps(run["request"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path, help="Neues Verzeichnis; bestehende Daten werden nie überschrieben")
    parser.add_argument("--seeds", nargs="+", type=seed_value, help="Optionale identische Seeds für beide Modelle")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        plan = write_bundle(args.output_dir.expanduser(), manifest, args.seeds)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"{len(plan['runs'])} Vergleichseinträge in {args.output_dir}; keine Renderjobs gestartet.")
    print("Krea Noct bleibt blockiert. Enthalten sind nur ausführbare Juggernaut-Requestdateien und ein leerer Bewertungsbogen.")


if __name__ == "__main__":
    main()
