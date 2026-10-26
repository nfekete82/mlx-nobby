from email.message import EmailMessage
import io
import os
from pathlib import Path
import tempfile

from backend import eml_anonymization_routes as eml


def test_eml_redaction_removes_header_and_attachment_preserves_reply():
    mail = EmailMessage()
    mail["From"] = "Erika Musterfrau <erika@example.org>"
    mail["To"] = "Support <info@example.org>"
    mail["Subject"] = "Anschlussgebühr Erika Musterfrau"
    mail["Message-ID"] = "<private@example.org>"
    mail.set_content("Sehr geehrte Frau Erika Musterfrau,\nBitte rufen Sie 0171 12345678 zurück.\nViele Grüße\nErika Musterfrau\n\nVon: Erika Musterfrau <erika@example.org>\nMeine Gebühr wurde nicht erstattet.")
    mail.add_attachment(b"secret", maintype="application", subtype="octet-stream", filename="vertrag.pdf")
    data, stripped = eml.redact(mail.as_bytes())
    result = EmailMessage()
    from email import policy, message_from_bytes
    out = message_from_bytes(data, policy=policy.default)
    decoded = out.get_content()
    assert stripped == 1
    assert "Musterfrau" not in data.decode("utf-8")
    assert "example.org" not in data.decode("utf-8")
    assert "0171" not in data.decode("utf-8")
    assert "Message-ID" not in data.decode("utf-8")
    assert "Meine Gebühr wurde nicht erstattet" in decoded
    assert "[NAME_" in decoded
    assert not out.get("From")


def test_html_only_email_and_no_original_metadata():
    mail = EmailMessage()
    mail["From"] = "Max Muster <max@example.com>"
    mail["Subject"] = "Ticket für Max Muster"
    mail.add_alternative("<html><body><p>Hallo Max Muster</p><p>Kontakt: max@example.com</p><script>secret()</script></body></html>",subtype="html")
    data, removed = eml.redact(mail.as_bytes())
    assert b"secret()" not in data
    assert b"max@example.com" not in data
    assert b"Max Muster" not in data
    assert b"[EMAIL_" in data
    assert removed == 0


def test_job_queue_processes_sequentially_and_exports(tmp_path, monkeypatch):
    monkeypatch.setattr(eml, "ROOT", tmp_path)
    monkeypatch.setattr(eml, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(eml, "OUTBOX", tmp_path / "redacted")
    m = EmailMessage()
    m.set_content("Eine Rufnummer 0171 12345678.")
    with eml.database() as db:
        db.execute("INSERT INTO jobs(id,name,state) VALUES(?,?,'queued')", ("a"*32,"mail.eml"))
    (eml.INBOX / ("a"*32+".eml")).write_bytes(m.as_bytes())
    eml.run_worker()
    assert (eml.OUTBOX / ("a"*32+".eml")).exists()
    with eml.database() as db:
        assert db.execute("SELECT state FROM jobs").fetchone()[0] == "done"
