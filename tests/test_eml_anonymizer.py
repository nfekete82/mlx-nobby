"""Privacy and resumable queue regression tests for EML anonymization."""
import io
import json
import sqlite3
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import eml_anonymizer as mod


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", tmp_path / "eml-store")
    monkeypatch.setattr(mod, "_READY", False)
    monkeypatch.setattr(mod, "_THREAD", None)
    mod.setup()
    yield mod
    thread = mod._THREAD
    if thread and thread.is_alive():
        mod.set_setting("running", "0")
        thread.join(timeout=3)


def example_mail():
    mail = EmailMessage()
    mail["From"] = "Max Mustermann <max.mustermann@example.de>"
    mail["To"] = "Erika Musterfrau <erika@example.com>"
    mail["Subject"] = "Anschlussgebühr: 0171 12345678"
    mail.set_content(
        "Sehr geehrte Frau Erika Musterfrau,\n"
        "für die Rufnummer 0171 12345678 wurde eine Gutschrift reklamiert.\n"
        "Meine Anschrift: Hauptstraße 12, 73033 Göppingen.\n"
        "Bitte schreiben Sie an erika@example.com.\n"
        "Viele Grüße\nMax Mustermann\n"
    )
    return mail


def test_eml_has_no_original_headers_or_contacts(isolated):
    raw = example_mail().as_bytes()
    data, warnings = isolated.anonymize(raw)
    clean = BytesParser(policy=policy.default).parsebytes(data)
    value = data.decode("utf-8")
    for private in ("Max Mustermann", "Erika Musterfrau", "example.com",
                    "example.de", "0171 12345678", "Hauptstraße 12",
                    "73033 Göppingen"):
        assert private not in value
    assert clean["From"] == "anonymisiert@invalid.example"
    assert clean["To"] == "anonymisiert@invalid.example"
    assert clean["X-MLX-Nobby-Review"] == "required"
    assert clean["Subject"].startswith("Anschlussgebühr")
    assert "Gutschrift reklamiert" in value
    assert warnings


def test_multipart_html_and_attachments_removed(isolated):
    mail = EmailMessage()
    mail["From"] = "Klara Muster <klara@example.org>"
    mail["To"] = "Info <info@example.org>"
    mail["Subject"] = "Anfrage"
    mail.set_content("Hallo Klara Muster, bitte klären.")
    mail.add_alternative("<html><head><style>.x{color:red}</style></head>"
                         "<body><script>PRIVATE_SCRIPT</script><p>Hallo Klara Muster</p>"
                         "</body></html>", subtype="html")
    mail.add_attachment(b"SENSITIVE_ATTACHMENT", maintype="application",
                        subtype="octet-stream", filename="private.pdf")
    data, warnings = isolated.anonymize(mail.as_bytes())
    assert b"SENSITIVE_ATTACHMENT" not in data
    assert b"PRIVATE_SCRIPT" not in data
    assert b"private.pdf" not in data
    assert b"klara@example.org" not in data
    assert any("ausgelassen" in warning for warning in warnings)


def test_html_only_strips_markup(isolated):
    mail = EmailMessage()
    mail["From"] = "Klara Muster <klara@example.org>"
    mail["Subject"] = "Hallo"
    mail.set_content("<html><body><p>Hallo Klara Muster</p></body></html>",
                     subtype="html")
    output, _ = isolated.anonymize(mail.as_bytes())
    assert b"<html>" not in output
    assert b"Klara Muster" not in output
    assert b"[PERSON_" in output


def test_upload_status_queue_export_and_purge(isolated):
    app = FastAPI()
    app.include_router(isolated.router)
    with TestClient(app) as client:
        original = example_mail().as_bytes()
        response = client.post("/api/eml-anonymizer/upload",
                               files={"file": ("private.eml", io.BytesIO(original),
                                               "message/rfc822")})
        assert response.status_code == 201
        assert client.get("/api/eml-anonymizer/status").json()["counts"]["queued"] == 1
        result = client.post("/api/eml-anonymizer/start",
                             json={"use_local_ai": False})
        assert result.status_code == 200
        import time
        state = client.get("/api/eml-anonymizer/status").json()
        for _ in range(80):
            if state["counts"].get("review") == 1:
                break
            time.sleep(0.05)
            state = client.get("/api/eml-anonymizer/status").json()
        assert state["counts"]["review"] == 1
        assert not state["running"]
        with client.stream("GET", "/api/eml-anonymizer/export") as download:
            assert download.status_code == 200
            archive = io.BytesIO(download.read())
        from zipfile import ZipFile
        with ZipFile(archive) as z:
            assert "email-000001.eml" in z.namelist()
            assert "ANONYMIZATION-REVIEW.json" in z.namelist()
            assert b"Max Mustermann" not in z.read("email-000001.eml")
            report = json.loads(z.read("ANONYMIZATION-REVIEW.json"))
            assert report[0]["review_required"]
        assert client.post("/api/eml-anonymizer/purge").json()["ok"]
        assert client.get("/api/eml-anonymizer/status").json()["counts"] == {}


def test_restart_requeues_processing(isolated, monkeypatch):
    original = isolated.ROOT / "incoming" / "aa.eml"
    original.write_bytes(example_mail().as_bytes())
    with isolated.db() as con:
        con.execute("INSERT INTO jobs (id,ordinal,size,state,created,updated) "
                    "VALUES ('aa',1,123,'processing',1,1)")
    monkeypatch.setattr(isolated, "_READY", False)
    isolated.setup()
    with isolated.db() as con:
        state = con.execute("SELECT state FROM jobs WHERE id='aa'").fetchone()[0]
    assert state == "queued"


def test_upload_rejects_other_types_and_does_not_log_name(isolated):
    app = FastAPI()
    app.include_router(isolated.router)
    with TestClient(app) as client:
        response = client.post("/api/eml-anonymizer/upload",
                               files={"file": ("person.pdf", b"not an eml", "application/pdf")})
        assert response.status_code == 415
        assert "person.pdf" not in str(response.json())
        with isolated.db() as con:
            assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_footer_removal_preserves_quoted_email(isolated):
    text = (
        "Die Gebühr wurde reklamiert.\n\nMit freundlichen Grüßen\n"
        "Max Mustermann\nFirma Beispiel GmbH\nGeschäftsführer: Uwe Muster\n"
        "Vertraulich und geheim.\n\nVon: Erika Musterfrau <erika@example.com>\n"
        "Die Anschlussgebühr wurde berechnet.\n"
    )
    stripped = isolated.strip_signature_blocks(text)
    assert "Firma Beispiel" not in stripped
    assert "Uwe Muster" not in stripped
    assert "Die Gebühr wurde reklamiert" in stripped
    assert "Die Anschlussgebühr wurde berechnet" in stripped
