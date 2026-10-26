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



def test_chat_batches_have_private_progress_and_scoped_downloads(isolated):
    app = FastAPI()
    app.include_router(isolated.router)
    batch_a = "a" * 32
    batch_b = "b" * 32
    with TestClient(app) as client:
        for batch in (batch_a, batch_b):
            res = client.post("/api/eml-anonymizer/upload",
                data={"batch_id": batch},
                files={"file": ("private.eml", io.BytesIO(example_mail().as_bytes()),
                                "message/rfc822")})
            assert res.status_code == 201
            assert res.json()["batch_id"] == batch
        assert client.get("/api/eml-anonymizer/batch/" + batch_a + "/status").json()["total"] == 1
        assert client.get("/api/eml-anonymizer/batch/" + batch_b + "/status").json()["total"] == 1
        assert client.get("/api/eml-anonymizer/batch/" + ("0" * 32) + "/status").status_code == 404
        assert client.get("/api/eml-anonymizer/batch/" + batch_a + "/export").status_code == 409
        assert client.post("/api/eml-anonymizer/start", json={"use_local_ai": False}).status_code == 200
        import time
        for _ in range(80):
            state = client.get("/api/eml-anonymizer/batch/" + batch_a + "/status").json()
            if state["finished"]:
                break
            time.sleep(.05)
        assert state["finished"]
        assert state["completed"] == 1
        for _ in range(80):
            state_b = client.get("/api/eml-anonymizer/batch/" + batch_b + "/status").json()
            if state_b["finished"]:
                break
            time.sleep(.05)
        assert state_b["completed"] == 1
        single = client.get("/api/eml-anonymizer/batch/" + batch_a + "/result")
        assert single.status_code == 200
        assert b"Max Mustermann" not in single.content
        assert "attachment;" in single.headers.get("content-disposition", "").lower()
        archive = client.get("/api/eml-anonymizer/batch/" + batch_a + "/export")
        assert archive.status_code == 200
        from zipfile import ZipFile
        with ZipFile(io.BytesIO(archive.content)) as zipfile:
            files = [name for name in zipfile.namelist() if name.endswith(".eml")]
            assert len(files) == 1
            assert b"Max Mustermann" not in zipfile.read(files[0])
        assert client.post("/api/eml-anonymizer/upload",
                data={"batch_id": "../../invalid"},
                files={"file": ("private.eml", b"some mail content", "message/rfc822")}).status_code == 400


def test_existing_queue_db_migrates_without_dropping_jobs(isolated, monkeypatch):
    with isolated.db() as con:
        con.execute("INSERT INTO jobs (id,ordinal,size,state,created,updated) "
                    "VALUES ('existing',1,100,'queued',1,1)")
        con.execute("ALTER TABLE jobs RENAME TO jobs_with_batch")
        con.execute("""CREATE TABLE jobs (
            id TEXT PRIMARY KEY, ordinal INTEGER NOT NULL,
            size INTEGER NOT NULL, state TEXT NOT NULL,
            warnings TEXT NOT NULL DEFAULT '[]',
            created REAL NOT NULL, updated REAL NOT NULL)""")
        con.execute("INSERT INTO jobs(id,ordinal,size,state,warnings,created,updated) "
                    "SELECT id,ordinal,size,state,warnings,created,updated FROM jobs_with_batch")
        con.execute("DROP TABLE jobs_with_batch")
    monkeypatch.setattr(isolated, "_READY", False)
    isolated.setup()
    with isolated.db() as con:
        columns = {row["name"] for row in con.execute("PRAGMA table_info(jobs)")}
        assert "batch_id" in columns
        row = con.execute("SELECT id,batch_id FROM jobs").fetchone()
        assert row["id"] == "existing"
        assert row["batch_id"] == ""



def test_legacy_and_mislabeled_charsets_keep_german_umlauts(isolated):
    base = (b"From: Info <info@example.org>\r\n"
            b"Subject: =?utf-8?Q?R=C3=BCckfrage_zur_Geb=C3=BChr?=\r\n"
            b"MIME-Version: 1.0\r\n")
    utf8_wrongly_latin1 = (base +
        b"Content-Type: text/plain; charset=iso-8859-1\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n" +
        "Viele Grüße, bitte für die Änderung prüfen.".encode("utf-8"))
    subject, text, _, _ = isolated.get_content(utf8_wrongly_latin1)
    assert "Rückfrage" in subject
    assert "Gebühr" in subject
    assert "Grüße" in text
    assert "Änderung" in text
    assert "Ã" not in text

    legacy_wrongly_utf8 = (base +
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n" +
        "Für die Gebühr sind 12 € gutgeschrieben.".encode("cp1252"))
    _, text, _, _ = isolated.get_content(legacy_wrongly_utf8)
    assert "Für die Gebühr" in text
    assert "€" in text
    assert "\ufffd" not in text
    assert isolated.repair_mojibake("Viele GrÃ¼ße, Größe und Ã„nderung") == \
        "Viele Grüße, Größe und Änderung"

    clean, _ = isolated.anonymize(utf8_wrongly_latin1)
    final = BytesParser(policy=policy.default).parsebytes(clean)
    assert "Grüße" in final.get_content()
    assert "Änderung" in final.get_content()


def test_faq_is_grounded_in_redacted_eml_and_downloadable(isolated, monkeypatch):
    observed = []
    def local_draft(prompt, max_tokens=850):
        observed.append(prompt)
        assert "Max Mustermann" not in prompt
        assert "Erika Musterfrau" not in prompt
        assert "erika@example.com" not in prompt
        return json.dumps({"items": [{
            "frage": "Wie wird die Anschlussgebühr gutgeschrieben?",
            "antwort": "Die Gutschrift wurde reklamiert; die Bestätigung steht noch aus.",
            "kategorie": "Mobilfunk",
            "status": "offen"
        }]}, ensure_ascii=False)
    monkeypatch.setattr(isolated, "local_chat_reply", local_draft)
    app = FastAPI()
    app.include_router(isolated.router)
    batch = "a" * 32
    with TestClient(app) as client:
        response = client.post("/api/eml-anonymizer/upload",
            data={"batch_id": batch},
            files={"file": ("private.eml", io.BytesIO(example_mail().as_bytes()),
                             "message/rfc822")})
        assert response.status_code == 201
        result = client.post("/api/eml-anonymizer/start", json={
            "use_local_ai": False, "create_faq": True, "batch_id": batch})
        assert result.status_code == 200
        import time
        for _ in range(100):
            state = client.get("/api/eml-anonymizer/batch/" + batch + "/status").json()
            if state["finished"]:
                break
            time.sleep(.05)
        assert state["finished"]
        assert state["faq_requested"]
        assert state["faq_ready"] == 1
        assert state["faq_failed"] == 0
        assert observed
        faq = client.get("/api/eml-anonymizer/batch/" + batch + "/faq")
        assert faq.status_code == 200
        markdown = faq.content.decode("utf-8")
        assert "Anschlussgebühr" in markdown
        assert "Mobilfunk" in markdown
        assert "Bestätigung steht noch aus" in markdown
        assert "Max Mustermann" not in markdown
        assert "Prüfpflichtig" in markdown
        assert "charset=utf-8" in faq.headers["content-type"]


def test_unavailable_faq_model_does_not_block_redacted_eml(isolated, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("local model not available")
    monkeypatch.setattr(isolated, "local_chat_reply", unavailable)
    app = FastAPI()
    app.include_router(isolated.router)
    batch = "b" * 32
    with TestClient(app) as client:
        assert client.post("/api/eml-anonymizer/upload",
            data={"batch_id": batch},
            files={"file": ("private.eml", io.BytesIO(example_mail().as_bytes()),
                            "message/rfc822")}).status_code == 201
        assert client.post("/api/eml-anonymizer/start", json={
            "use_local_ai": False, "create_faq": True, "batch_id": batch}).status_code == 200
        import time
        for _ in range(100):
            state = client.get("/api/eml-anonymizer/batch/" + batch + "/status").json()
            if state["finished"]:
                break
            time.sleep(.05)
        assert state["finished"]
        assert state["completed"] == 1
        assert state["faq_failed"] == 1
        assert client.get("/api/eml-anonymizer/batch/" + batch + "/result").status_code == 200
        assert client.get("/api/eml-anonymizer/batch/" + batch + "/faq").status_code == 503


def test_faq_rejects_missing_batch_and_preserves_legacy_jobs(isolated, monkeypatch):
    app = FastAPI()
    app.include_router(isolated.router)
    with TestClient(app) as client:
        response = client.post("/api/eml-anonymizer/start", json={
            "create_faq": True, "batch_id": ""})
        assert response.status_code == 404
        response = client.get("/api/eml-anonymizer/batch/" + ("f" * 32) + "/faq")
        assert response.status_code == 404
    with isolated.db() as con:
        con.execute("INSERT INTO jobs(id,ordinal,size,state,created,updated) "
                    "VALUES('legacy', 5, 123, 'queued', 1, 1)")
    monkeypatch.setattr(isolated, "_READY", False)
    isolated.setup()
    with isolated.db() as con:
        row = con.execute("SELECT faq_requested,faq_state FROM jobs WHERE id='legacy'").fetchone()
        assert row["faq_requested"] == 0
        assert row["faq_state"] == "off"
