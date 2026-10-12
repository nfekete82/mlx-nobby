"""Read-only diagnostic of originally captured evidence units."""
from agent.v15_evidence_inspection import evidence_inspection, inspect_saved_capture


def test_offline_support_row_diagnosis_preserves_context_not_truth_labels(tmp_path):
    import json
    text = (
        "Versioning Policy\n"
        "Version | Current minor | Supported | First Release | Final Release\n"
        "18 | 18.6 | Yes | 2025-09-25 | 2030-11-14\n"
        "17 | 17.11 | Yes | 2024-09-26 | 2029-11-08\n"
        "13 | 13.23 | No | 2020-09-24 | 2025-11-13\n"
        "No other version is asserted here.\n"
    )
    row = {
        "id": "CD02",
        "question": "Welche PostgreSQL-Hauptversionen werden auf der offiziellen PostgreSQL-Website derzeit unterstützt?",
        "response": {"steps": [
            {"action": "fetch_url", "status": "completed",
             "query": "https://www.postgresql.org/support/versioning/",
             "result": {"ok": True, "url": "https://www.postgresql.org/support/versioning/",
                        "text": text}},
        ]},
    }
    report = evidence_inspection(row)
    assert report["fetched_source_count"] == 1
    assert report["sources"][0]["support_window_count"] == 1
    assert report["sources"][0]["anchored_passage_count"] >= 1
    assert report["source_table_candidate_count"] == 2
    assert report["sources"][0]["exact_supported_table_candidates"] == [
        "PostgreSQL 18", "PostgreSQL 17",
    ]
    assert all(len(item["text"]) <= 190
               for item in report["sources"][0]["source_table_line_samples"])
    assert "No other version is asserted here." not in str(report["sources"][0]["exact_supported_table_candidates"])
    path = tmp_path / "capture.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    assert inspect_saved_capture(path)["reads_only_saved_capture"] is True


def test_missing_loaded_sources_cannot_be_reported_as_supported():
    row = {"id": "CD01", "question": "Welche Pixel-Smartphones?",
           "response": {"steps": [
               {"action": "fetch_url", "status": "completed",
                "result": {"ok": False, "text": ""}},
           ]}}
    report = evidence_inspection(row)
    assert report["fetched_source_count"] == 0
    assert report["sources"] == []



def test_diagnostic_never_echoes_unrelated_site_page_bodies():
    secret = "SECRET_NEVER_PRINT"
    row = {"id": "CD02",
           "question": "Welche PostgreSQL-Hauptversionen werden offiziell unterstützt?",
           "response": {"steps": [
               {"action": "fetch_url", "status": "completed",
                "query": "https://postgresql.org.evil.example/support/versioning/",
                "result": {"ok": True, "url": "https://postgresql.org.evil.example/support/versioning/",
                           "text": "Version | Current minor | Supported\n"
                                   "18 | 18.6 | Yes\n" + secret * 20}},
           ]}}
    report = evidence_inspection(row)
    assert report["source_table_candidate_count"] == 0
    assert report["sources"][0]["source_table_line_samples"] == []
    assert secret not in str(report)
