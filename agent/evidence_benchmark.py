"""Reproducible synthetic evidence benchmark; no network or LLM required.

Run: python -m agent.evidence_benchmark
JSON summary reports detector precision/recall, false alarms and missed errors.
Synthetic truth is explicitly defined per scenario, not inferred from the gate.
"""
import json
import time
from agent.claim_validation import audit_numerical_claims, gate_numerical_claims

URL = "https://example.org/evidence/"
MODELS = ("Pixel 11", "Galaxy S30", "iPhone 19 Pro", "MacBook M6", "ThinkPad X1")
BASE = "Product specifications and price reference. " * 4


def obs(*texts):
    return [
        {"action": "fetch_url", "status": "completed",
         "result": {"ok": True, "url": URL + str(i), "text": text}}
        for i, text in enumerate(texts)
    ]


def cases():
    """60 labeled cases across six failure patterns."""
    result = []
    for i in range(10):
        model = MODELS[i % len(MODELS)]
        other = MODELS[(i + 1) % len(MODELS)]
        price = 900 + 100 * i
        wrong = price + 50
        evidence = BASE + (model + " kostet " + str(price) + " €. ") * 4
        unrelated = BASE + (other + " kostet " + str(wrong) + " €. ") * 4
        definitions = [
            ("supported", model + " kostet " + str(price) + " €.",
             obs(evidence), False),
            ("unsupported", model + " kostet " + str(wrong) + " €.",
             obs(evidence), True),
            ("other_product", model + " kostet " + str(wrong) + " €.",
             obs(evidence + " " + unrelated), True),
            ("conflicting", model + " kostet " + str(price) + " €.",
             obs(evidence, BASE + (model + " kostet " + str(wrong) + " €. ") * 4), True),
            ("no_fetch", model + " kostet " + str(price) + " €.",
             [], False),
            ("undated_prediction", model + " kommt vermutlich nächstes Jahr.",
             obs(evidence), False),
        ]
        for category, answer, sources, should_flag in definitions:
            result.append({"id": f"{category}-{i:02d}", "category": category,
                           "answer": answer, "observations": sources,
                           "should_flag": should_flag})
    return result


def evaluate(rows=None):
    rows = cases() if rows is None else rows
    tp = fp = fn = tn = 0
    timings = []
    details = []
    for case in rows:
        start = time.perf_counter()
        audit = audit_numerical_claims(case["answer"], case["observations"])
        warning = bool(audit["unverified"] or audit.get("conflicts"))
        output = gate_numerical_claims(case["answer"], case["observations"])
        elapsed = (time.perf_counter() - start) * 1000
        timings.append(elapsed)
        truth = case["should_flag"]
        if truth and warning:
            tp += 1
        elif truth:
            fn += 1
        elif warning:
            fp += 1
        else:
            tn += 1
        details.append({"id": case["id"], "expected_flag": truth,
                        "flagged": warning, "warning_in_output": output != case["answer"],
                        "elapsed_ms": round(elapsed, 3)})
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"dataset": "synthetic-v1", "cases": len(rows),
            "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "precision": precision, "recall": recall,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
            "false_negative_rate": fn / (fn + tp) if fn + tp else None,
            "mean_audit_ms": sum(timings) / len(timings) if timings else None,
            "max_audit_ms": max(timings) if timings else None,
            "details": details}


def main():
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
