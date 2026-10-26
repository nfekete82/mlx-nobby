"""Local sequential EML redaction workspace. Not a guarantee of GDPR anonymization."""
from __future__ import annotations

import email
from email import policy
from email.headerregistry import Address
from email.utils import getaddresses
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid
import zipfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

ROOT = Path(os.environ.get("NOBBY_EML_DIR", "/app-data/eml"))
INBOX, OUTBOX = ROOT / "inbox", ROOT / "redacted"
LOCK = threading.Lock()
WORKER = None
MAX_EML = 25 * 1024 * 1024
PATTERNS = [
    ("EMAIL", re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.I)),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9][ ]?){11,30}\b")),
    ("WEB", re.compile(r"https?://[^\s<>\"']+|\bwww\.[^\s<>\"']+", re.I)),
    ("TELEFON", re.compile(r"(?<!\w)(?:\+\d{1,3}[ /-]?|0)[\d /()-]{7,}\d(?!\w)")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("PLZ_ORT", re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+(?:[ -][A-ZÄÖÜ][a-zäöüß]+)*")),
    ("ADRESSE", re.compile(r"\b[A-ZÄÖÜ][\wäöüß.-]*(?:straße|strasse|weg|platz|allee|gasse)\s+\d+[a-z]?\b", re.I)),
]
SALUTATION = re.compile(r"\b(?:Sehr geehrte(?:r)?|Liebe(?:r)?|Hallo|Guten Tag[,]?)\s+(?:Frau|Herrn?|Dr\.)?\s*([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){0,2})")
SIGNOFF = re.compile(r"(?im)^\s*(?:Mit freundlichen Grüßen|Freundliche Grüße|Viele Grüße|Best regards|Kind regards)\s*$")
router = APIRouter(prefix="/api/mlx/eml", tags=["eml-redaction"])


class TextFromHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.skip += 1
        if tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def database():
    ROOT.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / "jobs.sqlite3", timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, name TEXT NOT NULL, state TEXT NOT NULL, error TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)")
    db.commit()
    return db


def replace_identifiers(text, people=()):
    values = {}
    counter = {}
    def sub(label, value):
        key = (label, value.casefold())
        if key not in values:
            counter[label] = counter.get(label, 0) + 1
            values[key] = f"[{label}_{counter[label]}]"
        return values[key]
    for name in sorted(set(people), key=len, reverse=True):
        if len(name) >= 4:
            text = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", lambda m: sub("NAME", m.group()), text, flags=re.I)
    for label, pattern in PATTERNS:
        text = pattern.sub(lambda m: sub(label, m.group()), text)
    text = SALUTATION.sub(lambda m: m.group(0).replace(m.group(1), sub("NAME", m.group(1))), text)
    return text


def redact(raw):
    message = email.message_from_bytes(raw, policy=policy.default)
    names = []
    for key in ("From", "To", "Cc", "Bcc", "Reply-To"):
        for name, _ in getaddresses(message.get_all(key, [])):
            if name.strip():
                names.append(name.strip().strip('"'))
    fragments = []
    html_parts = []
    stripped_attachments = 0
    for part in message.walk():
        if part.is_multipart():
            continue
        kind = part.get_content_type()
        if part.get_content_disposition() == "attachment" or part.get_filename():
            stripped_attachments += 1
            continue
        if kind not in ("text/plain", "text/html"):
            stripped_attachments += 1
            continue
        try:
            payload = part.get_content()
            if not isinstance(payload, str):
                continue
        except Exception:
            continue
        if kind == "text/plain":
            fragments.append(payload)
        else:
            parser = TextFromHTML()
            parser.feed(payload)
            html_parts.append("".join(parser.parts))
    body = "\n".join(fragments or html_parts)
    # Signatures and long legal footer text have no support value.
    match = SIGNOFF.search(body)
    if match:
        body = body[:match.start()]
    if not body.strip():
        raise ValueError("No readable text/plain or text/html body")
    subject = replace_identifiers(str(message.get("Subject", "")), names)
    clean = replace_identifiers(body, names)
    # Emit a new minimal email: no original MIME tree, addresses, dates or IDs.
    result = email.message.EmailMessage(policy=policy.default)
    result["Subject"] = subject
    result.set_content(clean)
    return result.as_bytes(), stripped_attachments


def run_worker():
    global WORKER
    while True:
        with database() as db:
            row = db.execute("SELECT id FROM jobs WHERE state IN ('queued', 'processing') ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return
            job_id = row[0]
            db.execute("UPDATE jobs SET state='processing',error=NULL WHERE id=?", (job_id,))
        try:
            raw = (INBOX / (job_id + ".eml")).read_bytes()
            data, removed = redact(raw)
            target = OUTBOX / (job_id + ".eml")
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(target)
            with database() as db:
                db.execute("UPDATE jobs SET state='done',error=? WHERE id=?", (f"{removed} attachment/non-text parts excluded; review required",job_id))
        except Exception as exc:
            with database() as db:
                db.execute("UPDATE jobs SET state='failed',error=? WHERE id=?", (type(exc).__name__ + ": " + str(exc)[:150],job_id))


def kick():
    global WORKER
    with LOCK:
        if WORKER is None or not WORKER.is_alive():
            WORKER = threading.Thread(target=run_worker, daemon=True, name="eml-redaction")
            WORKER.start()


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    name = Path(file.filename or "").name
    if not name.lower().endswith(".eml") or not name or len(name) > 200:
        raise HTTPException(400, "Only .eml files are accepted")
    ident = uuid.uuid4().hex
    with database() as db:
        destination = INBOX / (ident + ".eml")
        size = 0
        try:
            with destination.open("xb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_EML:
                        raise HTTPException(413, "EML exceeds 25 MB")
                    out.write(chunk)
            if not size:
                raise HTTPException(400, "Empty EML")
            db.execute("INSERT INTO jobs(id,name,state) VALUES(?,?,'queued')", (ident,name))
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    kick()
    return {"id":ident,"name":name,"state":"queued"}


@router.get("/status")
def status():
    with database() as db:
        rows = db.execute("SELECT id,name,state,error FROM jobs ORDER BY created,id DESC LIMIT 500").fetchall()
        counts = dict(db.execute("SELECT state,count(*) FROM jobs GROUP BY state").fetchall())
    if counts.get("queued") or counts.get("processing"):
        kick()
    return {"counts":counts,"recent":[{"id":a,"name":b,"state":c,"note":d} for a,b,c,d in rows],"review_required":True}


@router.get("/export.zip")
def export_zip():
    def chunks():
        # Zip assembled on persistent disk, not in RAM.
        import tempfile
        with tempfile.TemporaryFile() as output:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                with database() as db:
                    rows = db.execute("SELECT id,name FROM jobs WHERE state='done' ORDER BY created,id").fetchall()
                for ident, name in rows:
                    source = OUTBOX / (ident + ".eml")
                    if source.is_file():
                        archive.write(source, arcname=ident + ".eml")
                archive.writestr("REVIEW_REQUIRED.txt","Automated redaction is not verified anonymization. Attachments excluded. Manually review before external use.\n")
            output.seek(0)
            while data := output.read(1024 * 1024):
                yield data
    return StreamingResponse(chunks(),media_type="application/zip",headers={"Content-Disposition":'attachment; filename="nobby-eml-redacted.zip"'})


def install_routes(app):
    app.include_router(router)
    @app.get("/eml-anonymisierung", response_class=HTMLResponse)
    def eml_page():
        return FileResponse(Path(__file__).resolve().parent.parent / "frontend" / "eml-anonymisierung.html")
