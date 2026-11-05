"""Conflict audit must redact raw personal values and identity-bearing subjects."""
from pathlib import Path
import runpy

AUDIT = Path(__file__).resolve().parents[1] / "scripts" / "audit-memory-conflicts-local.py"


def test_grouped_conflicts_never_return_sensitive_text():
    functions = runpy.run_path(str(AUDIT), run_name="safe_fixture")
    aggregate = functions["aggregate"]
    rows = [
        {"fact_id": "x", "subject": "ich", "field": "gesundheit",
         "value": "fictional-secret-value", "previous_value": "fictional-secret-value",
         "proposed_value": "private-text"},
        {"fact_id": "x", "subject": "ich", "field": "gesundheit",
         "proposed_value": "another-private-text"},
        {"fact_id": "y", "subject": "personen.private-name", "field": "status"},
        {"fact_id": "z", "subject": "projekte.internal-project", "field": "status"},
    ]
    per_field, grouped, repeated = aggregate(rows)
    assert per_field["gesundheit"] == 2
    assert per_field["status"] == 2
    assert grouped[("status", "personen")] == 1
    assert grouped[("status", "projekte")] == 1
    assert repeated == 1
    rendered = repr((per_field, grouped, repeated))
    for private_value in ("fictional-secret-value", "private-text",
                          "private-name", "internal-project", "x", "y", "z"):
        assert private_value not in rendered


def test_no_named_project_or_person_in_anonymous_report():
    functions = runpy.run_path(str(AUDIT), run_name="safe_fixture")
    group = functions["subject_group"]
    assert group("ich") == "ich"
    assert group("partner") == "partner"
    assert group("familie.sohn") == "familie"
    assert group("personen.example-user") == "personen"
    assert group("projekte.private-project") == "projekte"
    assert functions["field_root"]("gesundheit.fakehash") == "gesundheit"
