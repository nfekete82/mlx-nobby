"""Synthetic local tests for bounded Office/ZIP inspection and edits."""
from io import BytesIO
from pathlib import Path
import os
import stat
import zipfile

import pytest
from docx import Document
from openpyxl import Workbook, load_workbook
from backend import office_workspace as office
from backend import office_routes


def word_bytes():
    doc = Document()
    doc.add_paragraph("Kunde MUSTER: Altstadt")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Ort"
    table.cell(0, 1).text = "Altstadt"
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def excel_bytes():
    book = Workbook()
    sheet = book.active
    sheet["A1"] = "Altstadt"
    sheet["B1"] = "=1+2"
    sheet["C1"] = 123
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def archive_bytes(filename="notes.txt", payload=b"Altstadt"):
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(filename, payload)
    return out.getvalue()


def test_docx_preserves_structure_and_edits_original_copy():
    source = word_bytes()
    info = office.inspect(source, "letter.docx")
    assert "Altstadt" in info.preview
    changed, count = office.edit(source, "letter.docx", [{"old": "Altstadt", "new": "Neustadt"}])
    assert count == 2
    assert changed != source
    before = Document(BytesIO(source))
    after = Document(BytesIO(changed))
    assert "Altstadt" in before.paragraphs[0].text
    assert "Neustadt" in after.paragraphs[0].text
    assert after.tables[0].cell(0, 1).text == "Neustadt"


def test_xlsx_preserves_formulas_and_values():
    source = excel_bytes()
    assert "A1=Altstadt" in office.inspect(source, "book.xlsx").preview
    out, count = office.edit(source, "book.xlsx", [{"old": "Altstadt", "new": "Neustadt"}])
    assert count == 1
    book = load_workbook(BytesIO(out))
    assert book.active["A1"].value == "Neustadt"
    assert book.active["B1"].value == "=1+2"
    assert book.active["C1"].value == 123


def test_zip_changes_text_member_without_changing_binary_member():
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("notes.txt", "Altstadt")
        zf.writestr("image.png", b"\x89PNG\x00\xff")
    source = out.getvalue()
    info = office.inspect(source, "archive.zip")
    assert info.files == 2
    result, count = office.edit(source, "archive.zip", [{"old": "Altstadt", "new": "Neustadt"}])
    assert count == 1
    with zipfile.ZipFile(BytesIO(result)) as zf:
        assert zf.read("notes.txt") == b"Neustadt"
        assert zf.read("image.png") == b"\x89PNG\x00\xff"


@pytest.mark.parametrize("path", ["../private.txt", "/absolute.txt", "C:/drive.txt"])
def test_zip_rejects_unsafe_member_names(path):
    with pytest.raises(office.OfficeError, match="UNSAFE_ZIP_PATH"):
        office.inspect(archive_bytes(path), "data.zip")


def test_zip_rejects_symlink():
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        member = zipfile.ZipInfo("shortcut")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(member, "target")
    with pytest.raises(office.OfficeError, match="ZIP_SYMLINK_BLOCKED"):
        office.inspect(out.getvalue(), "data.zip")


def test_reject_invalid_plan_and_readonly_legacy_excel():
    with pytest.raises(office.OfficeError, match="INVALID_EDIT_PLAN"):
        office.validated_replacements([{"old": "", "new": "x"}])
    with pytest.raises(office.OfficeError, match="DUPLICATE_EDIT"):
        office.validated_replacements([{"old": "x", "new": "a"}, {"old": "x", "new": "b"}])
    with pytest.raises(office.OfficeError, match="READ_ONLY_FORMAT"):
        office.edit(b"legacy", "legacy.xls", [{"old": "a", "new": "b"}])


def test_model_response_is_not_executeable_instruction(monkeypatch, tmp_path):
    from backend import app as web
    monkeypatch.setattr(office_routes, "OUTPUT_ROOT", tmp_path)

    def model(_method, _route, payload=None, timeout=None):
        assert payload["messages"][0]["role"] == "system"
        assert "untrusted" in payload["messages"][0]["content"]
        assert "/api/runtime/chat" == _route
        return {"choices": [{"message": {"content":
            '{"summary":"Text geprüft", "replacements":[{"old":"Altstadt","new":"Neustadt"}]}'}}]}

    monkeypatch.setattr(web, "agent_json_request", model)
    result = office_routes._work(word_bytes(), "test.docx", "Ersetze Altstadt durch Neustadt")
    assert result["status"] == "modified"
    assert result["changes"] == 2
    assert result["download_url"].startswith("/api/mlx/office/download/")
    name = result["download_url"].rsplit("/", 1)[-1]
    path = office_routes.OUTPUT_ROOT / name
    assert path.is_file()
    path.unlink()


def test_no_model_edit_when_only_inspecting(monkeypatch):
    from backend import app as web

    monkeypatch.setattr(web, "agent_json_request", lambda *a, **k: {
        "choices": [{"message": {"content":
            '{"summary":"Prüfung abgeschlossen", "replacements":[{"old":"Altstadt","new":"Neustadt"}]}'}}]})
    response = office_routes._work(word_bytes(), "doc.docx", "Bitte prüfen")
    assert response["status"] == "completed"
    assert response["changes"] == 0
    assert response["download_url"] is None



def test_xlsx_rejects_generated_formula_string():
    source = excel_bytes()
    with pytest.raises(office.OfficeError, match="FORMULA_INJECTION_BLOCKED"):
        office.edit(source, "book.xlsx", [{"old": "Altstadt", "new": "=HYPERLINK(1,2)"}])


def test_zipped_office_rejects_archive_bomb_preflight():
    payload = b"X" * (office.MAX_ARCHIVE_UNPACKED + 1024)
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", payload)
    with pytest.raises(office.OfficeError, match="ZIP_TOO_LARGE"):
        office.inspect(out.getvalue(), "bomb.docx")


def test_process_and_download_api_without_real_model(monkeypatch, tmp_path):
    import asyncio
    import httpx
    from backend import app as web

    monkeypatch.setattr(office_routes, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(web, "agent_json_request", lambda *a, **k: {
        "choices": [{"message": {"content":
            '{"summary":"Changed literal", "replacements":[{"old":"Altstadt","new":"Neustadt"}]}'}}]})

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=web.app),
            base_url="http://localhost"
        ) as client:
            result = await client.post(
                "/api/mlx/office/process",
                files={"file": ("test.docx", word_bytes(),
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                data={"instruction": "Ersetze Altstadt durch Neustadt"},
            )
            assert result.status_code == 200, result.text
            payload = result.json()
            assert payload["status"] == "modified"
            assert payload["changes"] == 2
            assert payload["download_url"].startswith("/api/mlx/office/download/")
            downloaded = await client.get(payload["download_url"])
            assert downloaded.status_code == 200
            assert "Neustadt" in Document(BytesIO(downloaded.content)).paragraphs[0].text
            blocked = await client.get("/api/mlx/office/download/not-a-valid-token.zip")
            assert blocked.status_code == 404

    asyncio.run(scenario())



def test_zip_rejects_duplicate_paths():
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("config.txt", "first")
        zf.writestr("config.txt", "second")
    with pytest.raises(office.OfficeError, match="ZIP_DUPLICATE_PATH"):
        office.inspect(out.getvalue(), "duplicate.zip")


def test_model_cannot_edit_text_outside_supplied_excerpt(monkeypatch):
    from backend import app as web

    monkeypatch.setattr(web, "agent_json_request", lambda *a, **k: {
        "choices": [{"message": {"content":
            '{"summary":"Change", "replacements":[{"old":"not visible content","new":"wrong"}]}'}}]})
    with pytest.raises(office.OfficeError, match="EDIT_TEXT_NOT_IN_MODEL_EXCERPT"):
        office_routes._work(word_bytes(), "doc.docx", "Ersetze Altstadt")



def test_plain_model_text_allowed_for_readonly_inspection(monkeypatch):
    from backend import app as web

    monkeypatch.setattr(web, "agent_json_request", lambda *a, **k: {
        "choices": [{"message": {"content": "Only an inspection summary, not JSON"}}]})
    result = office_routes._work(word_bytes(), "review.docx", "Bitte analysieren")
    assert result["status"] == "completed"
    assert result["summary"] == "Only an inspection summary, not JSON"
    assert result["download_url"] is None


def test_plain_model_text_does_not_permit_edits(monkeypatch):
    from backend import app as web

    monkeypatch.setattr(web, "agent_json_request", lambda *a, **k: {
        "choices": [{"message": {"content": "Changed it already"}}]})
    with pytest.raises(office.OfficeError, match="MODEL_RESPONSE_INVALID"):
        office_routes._work(word_bytes(), "review.docx", "Ersetze Altstadt")
