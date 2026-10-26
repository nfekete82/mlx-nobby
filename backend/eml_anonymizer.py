"""Local, sequential EML anonymization. No remote services and no source-content logs.

Outputs deliberately contain only a newly constructed text/plain message.
Attachments, original headers and embedded HTML are never copied to outputs.
All output is review-required: automatic de-identification is not a guarantee.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from urllib.parse import urlsplit
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from time import time
from urllib.request import Request, urlopen

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

router = APIRouter(prefix="/api/eml-anonymizer", tags=["eml-anonymizer"])
ROOT = Path(os.environ.get("NOBBY_EML_DATA_DIR", "/app/eml-data"))
MAX_FILE = 30 * 1024 * 1024
MAX_TOTAL = 20 * 1024**3
CHUNK = 1024 * 1024
_LOCK = Lock()
_READY = False
_THREAD = None
_UPLOAD_LOCK = Lock()


class HtmlText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        if not self.skip and tag in ("p", "br", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1
        if not self.skip and tag in ("p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


@contextmanager
def db():
    connection = sqlite3.connect(ROOT / "queue.sqlite3", timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def setup():
    global _READY
    with _LOCK:
        if _READY:
            return
        ROOT.mkdir(parents=True, exist_ok=True)
        os.chmod(ROOT, 0o700)
        for folder in ("incoming", "outgoing", "temporary"):
            (ROOT / folder).mkdir(exist_ok=True)
        with db() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, ordinal INTEGER NOT NULL,
                size INTEGER NOT NULL, state TEXT NOT NULL,
                warnings TEXT NOT NULL DEFAULT '[]',
                created REAL NOT NULL, updated REAL NOT NULL
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )""")
            con.execute("UPDATE jobs SET state='queued' WHERE state='processing'")
            con.execute("INSERT OR IGNORE INTO settings VALUES ('running', '0')")
            con.execute("INSERT OR IGNORE INTO settings VALUES ('ai', '0')")
        _READY = True


def setting(key):
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else "0"


def set_setting(key, value):
    with db() as con:
        con.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def placeholders():
    counters = defaultdict(int)
    mapping = {}

    def put(kind, value):
        val = value.strip()
        key = (kind, val.casefold())
        if key not in mapping:
            counters[kind] += 1
            mapping[key] = f"[{kind}_{counters[kind]}]"
        return mapping[key]
    return put


RE_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")
RE_URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"']+")
RE_IBAN = re.compile(r"(?i)\b[A-Z]{2}\d{2}(?:[ \-]?[A-Z0-9]){11,30}\b")
RE_PHONE = re.compile(r"(?<![\w])(?:\+49|0049|0)[\s()\/.-]*(?:\d[\s()\/.-]*){7,15}(?!\w)")
RE_IP = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
RE_DATE = re.compile(r"\b(?:[0-3]?\d[./-][01]?\d[./-](?:19|20)?\d{2}|(?:19|20)\d{2}-[01]\d-[0-3]\d)\b")
RE_TIME = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b")
RE_POST = re.compile(r"\b\d{5}\s+[\wÄÖÜäöüß\- ]{3,35}(?=\n|,|$)")
RE_STREET = re.compile(r"(?im)\b[A-ZÄÖÜ][\wÄÖÜäöüß\- ]{2,55}"
                       r"(?:straße|strasse|weg|allee|platz|gasse|ring|str\.)\s*\d+[a-zA-Z]?\b")
RE_REGISTER = re.compile(r"(?i)\b(?:HRB|HRA|USt[- .]?IdNr\.?|Steuernummer|Kundennummer|"
                         r"Vertragsnummer|Auftragsnummer|Kunden[- ]?Nr\.?)\s*[:#.]?\s*[A-Z0-9/-]{3,}\b")
RE_GREETING = re.compile(r"(?im)\b(?:Sehr geehrte(?:r)?|Liebe(?:r)?|Hallo)\s+"
                         r"(?:Frau|Herrn?|Dr\.|Prof\.)?\s*"
                         r"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){0,3})")
RE_FROM = re.compile(r"(?im)^(?:Von|From|Gesendet von|Absender):\s*"
                     r"([^<\n]{3,90})(?=\s*<|$)")
RE_SIGNOFF = re.compile(r"(?im)(?:Viele Grüße|Mit freundlichen Grüßen|Beste Grüße|"
                        r"Freundliche Grüße|Kind regards|Best regards)\s*\n"
                        r"\s*([A-ZÄÖÜ][a-zäöüß\-]+\s+[A-ZÄÖÜ][a-zäöüß\-]+)\s*(?=\n|$)")
RE_ORG = re.compile(r"\b[A-ZÄÖÜ][\wÄÖÜäöüß&.,\- ]{2,65}\s"
                    r"(?:GmbH|UG|AG|e\.V\.|KG|OHG)\b")
RE_SIGNATURE = re.compile(r"(?im)^.*(?:Amtsgericht|Geschäftsführer:|Prokurist:|"
                          r"HRB:|USt-IdNr:|Datenschutzhinweis|"
                          r"This e-mail may contain confidential|"
                          r"Diese E-Mail enthält vertraulich).*$")


RE_FOOTER_BEGIN = re.compile(
    r"(?i)^(?:--\s*|Mit freundlichen Gr(?:ü|ue)ßen[,!]?|Viele Gr(?:ü|ue)ße[,!]?|"
    r"Beste Gr(?:ü|ue)ße[,!]?|Freundliche Gr(?:ü|ue)ße[,!]?|"
    r"Kind regards[,]?|Best regards[,]?)\s*$"
)
RE_QUOTED_MESSAGE = re.compile(
    r"(?i)^(?:Von:|From:|-----Original Message-----|"
    r"Am\s+.+\s+schrieb\b|On\s+.+\s+wrote:)"
)


def strip_signature_blocks(text):
    """Drop footer bodies, but keep subsequent quoted customer correspondence."""
    result = []
    skipping = False
    for line in text.splitlines():
        stripped = line.strip()
        if skipping:
            if not RE_QUOTED_MESSAGE.search(stripped):
                continue
            skipping = False
        if RE_FOOTER_BEGIN.fullmatch(stripped):
            result.append("[SIGNATUR ENTFERNT]")
            skipping = True
        else:
            result.append(line)
    return "\n".join(result)


def redact(text, *, headers=(), ai_spans=(), replace=None):
    replace = replace or placeholders()
    text = text.replace("\x00", "")
    candidates = []
    for name in headers:
        if 2 <= len(name.strip()) <= 100 and not re.search(
            r"(?i)\b(info|service|support|team|kontakt|noreply)\b", name
        ):
            candidates.append(name.strip().strip('"'))
    for pattern in (RE_GREETING, RE_FROM, RE_SIGNOFF):
        candidates.extend(m.group(1).strip(" ,;\"") for m in pattern.finditer(text))
    candidates.extend(str(name).strip() for name in ai_spans if isinstance(name, str))
    # Whole substrings only; avoid matching names inside product codes/words.
    for name in sorted(set(candidates), key=len, reverse=True):
        if len(name) < 3 or len(name) > 100 or not re.search(r"[a-zäöüß]", name):
            continue
        escaped = re.escape(name)
        text = re.sub(r"(?<![\w])" + escaped + r"(?![\w])",
                      lambda match: replace("PERSON", match.group()), text,
                      flags=re.IGNORECASE)
    for pattern, kind in (
        (RE_EMAIL, "EMAIL"), (RE_URL, "WEB"), (RE_IBAN, "IBAN"),
        (RE_PHONE, "TELEFON"), (RE_IP, "IP"), (RE_STREET, "ADRESSE"),
        (RE_POST, "ORT"), (RE_REGISTER, "REFERENZ"),
        (RE_ORG, "FIRMA"), (RE_DATE, "DATUM"), (RE_TIME, "ZEIT"),
    ):
        text = pattern.sub(lambda m, k=kind: replace(k, m.group()), text)
    # Administrative signatures contain little reusable support information.
    text = RE_SIGNATURE.sub("[SIGNATUR ENTFERNT]", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    return text


def get_content(raw):
    try:
        original = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception as exc:
        raise ValueError("Unlesbare EML-Struktur") from exc
    if not original.keys() or len(raw) < 10:
        raise ValueError("Keine gültige EML-Nachricht")
    names = []
    for field in ("From", "To", "Cc", "Bcc", "Sender", "Reply-To"):
        names.extend(name for name, _ in getaddresses(original.get_all(field, [])) if name)
    plain = []
    html = []
    attachment_count = 0
    for part in original.walk():
        if part.is_multipart():
            continue
        if part.get_content_disposition() == "attachment" or part.get_filename():
            attachment_count += 1
            continue
        typ = part.get_content_type()
        if typ not in {"text/plain", "text/html"}:
            attachment_count += 1
            continue
        try:
            body = part.get_content()
            if not isinstance(body, str):
                continue
            if typ == "text/plain":
                plain.append(body)
            else:
                parser = HtmlText()
                parser.feed(body)
                html.append("".join(parser.parts))
        except Exception:
            raise ValueError("Textteil konnte nicht dekodiert werden")
    body = "\n\n".join(plain if plain else html).strip()
    if not body:
        raise ValueError("Kein lesbarer Text; Anhänge werden nicht verarbeitet")
    return str(original.get("Subject") or ""), body, names, attachment_count


def local_ai_spans(text):
    """Optional one-shot local entity suggestions; never trust model output as a rewrite."""
    import urllib.error
    agent = os.environ.get("AGENT_URL", "http://host.docker.internal:8010").rstrip("/")
    # Route must remain inside the existing host-agent bridge.
    parsed = urlsplit(agent)
    if (parsed.scheme != "http" or parsed.hostname not in
            {"host.docker.internal", "127.0.0.1", "localhost"}
            or parsed.port != 8010 or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise RuntimeError("Lokaler MLX-Agent nicht konfiguriert")
    with urlopen(agent + "/api/status", timeout=5) as response:
        model = json.load(response).get("model")
    if not isinstance(model, str) or not model:
        raise RuntimeError("Kein lokales Chatmodell aktiv")
    prompt = ("Liste nur PERSONENNAMEN und konkrete STRASSEN-/ORTSNAMEN im Text. "
              "Antworte ausschließlich als JSON-Objekt mit Array 'entities' aus "
              "exakten zusammenhängenden Teilstrings des Texts. "
              "Keine Ergänzungen, keine Beschreibung.\n\n" + text[:12000])
    req = Request(agent + "/api/bridge/mlx/v1/chat/completions",
                  data=json.dumps({"model": model, "temperature": 0,
                                   "max_tokens": 600,
                                   "messages": [{"role": "user", "content": prompt}]},
                                  ensure_ascii=False).encode("utf-8"),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=180) as response:
        reply = json.load(response)["choices"][0]["message"]["content"]
    match = re.search(r"\{[\s\S]*\}", reply or "")
    if not match:
        raise ValueError("Lokales Modell lieferte kein JSON")
    entities = json.loads(match.group()).get("entities", [])
    if not isinstance(entities, list):
        raise ValueError("Ungültige KI-Entitäten")
    return [e for e in entities[:80] if isinstance(e, str) and 3 <= len(e) <= 100
            and e in text]


def anonymize(raw, use_ai=False):
    subject, body, names, attachment_count = get_content(raw)
    body = strip_signature_blocks(body)
    warnings = ["Automatische Anonymisierung: manuelle Datenschutzprüfung erforderlich"]
    if attachment_count:
        warnings.append(f"{attachment_count} Anhänge/andere MIME-Teile ausgelassen")
    suggested = []
    if use_ai:
        try:
            suggested = local_ai_spans(body)
            if len(body) > 12000:
                warnings.append("KI-Prüfung nur für erste 12000 Zeichen")
        except Exception:
            warnings.append("Lokale KI nicht verfügbar; nur regelbasierte Erkennung")
    replace = placeholders()
    clean_subject = redact(subject, headers=names, ai_spans=suggested, replace=replace)
    clean_body = redact(body, headers=names, ai_spans=suggested, replace=replace)
    output = EmailMessage()
    output["From"] = "anonymisiert@invalid.example"
    output["To"] = "anonymisiert@invalid.example"
    output["Subject"] = clean_subject or "[BETREFF ENTFERNT]"
    output["X-MLX-Nobby-Review"] = "required"
    output.set_content(clean_body, charset="utf-8")
    return output.as_bytes(policy=policy.SMTP), warnings


def worker():
    global _THREAD
    try:
        while setting("running") == "1":
            with db() as con:
                item = con.execute(
                    "SELECT id FROM jobs WHERE state='queued' ORDER BY ordinal LIMIT 1"
                ).fetchone()
                if item:
                    identifier = item["id"]
                    con.execute("UPDATE jobs SET state='processing', updated=? WHERE id=?",
                                (time(), identifier))
            if not item:
                set_setting("running", "0")
                return
            source = ROOT / "incoming" / (identifier + ".eml")
            target = ROOT / "outgoing" / (identifier + ".eml")
            try:
                raw = source.read_bytes()
                output, warnings = anonymize(raw, use_ai=setting("ai") == "1")
                temporary = ROOT / "temporary" / (identifier + ".tmp")
                temporary.write_bytes(output)
                os.replace(temporary, target)
                state = "review"
            except Exception:
                # Do not record raw email, original filename or exception content.
                warnings = ["E-Mail nicht verarbeitet; Quelldatei zur Prüfung behalten"]
                state = "failed"
            with db() as con:
                con.execute("UPDATE jobs SET state=?,warnings=?,updated=? WHERE id=?",
                            (state, json.dumps(warnings, ensure_ascii=False), time(),
                             identifier))
    finally:
        with _LOCK:
            _THREAD = None


def launch():
    global _THREAD
    setup()
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            if setting("running") == "1":
                _THREAD = threading.Thread(target=worker, daemon=True,
                                           name="eml-anonymizer")
                _THREAD.start()


class StartOptions(BaseModel):
    use_local_ai: bool = False


@router.get("/status")
def status():
    setup()
    launch()
    with db() as con:
        rows = con.execute("SELECT state, COUNT(*) AS count FROM jobs "
                           "GROUP BY state").fetchall()
        total = con.execute("SELECT COALESCE(SUM(size),0) FROM jobs").fetchone()[0]
        finished = con.execute("SELECT COUNT(*) FROM jobs WHERE state='review'").fetchone()[0]
    return {"counts": {r["state"]: r["count"] for r in rows},
            "total_bytes": total, "completed": finished,
            "running": setting("running") == "1",
            "ai": setting("ai") == "1",
            "review_required": True}


@router.post("/upload", status_code=201)
async def upload(file: UploadFile = File(...)):
    setup()
    if not (file.filename or "").lower().endswith(".eml"):
        raise HTTPException(415, "Nur .eml-Dateien erlaubt")
    if (ROOT / "queue.sqlite3").is_symlink():
        raise HTTPException(500, "Ungültiger Speicherpfad")
    identifier = uuid.uuid4().hex
    temporary = ROOT / "temporary" / (identifier + ".upload")
    size = 0
    try:
        with open(temporary, "xb") as target:
            os.chmod(temporary, 0o600)
            while data := await file.read(CHUNK):
                size += len(data)
                if size > MAX_FILE:
                    raise HTTPException(413, "EML-Datei größer als 30 MiB")
                target.write(data)
        if size < 10:
            raise HTTPException(422, "Leere oder ungültige EML")
        with _UPLOAD_LOCK:
            with db() as con:
                aggregate = con.execute(
                    "SELECT COALESCE(SUM(size),0) FROM jobs").fetchone()[0]
                if aggregate + size > MAX_TOTAL:
                    raise HTTPException(413, "Gesamtimport größer als 20 GiB")
                ordinal = con.execute(
                    "SELECT COALESCE(MAX(ordinal),0)+1 FROM jobs").fetchone()[0]
                os.replace(temporary, ROOT / "incoming" / (identifier + ".eml"))
                con.execute("INSERT INTO jobs(id,ordinal,size,state,created,updated) "
                            "VALUES(?,?,?,?,?,?)",
                            (identifier, ordinal, size, "queued", time(), time()))
    finally:
        temporary.unlink(missing_ok=True)
        await file.close()
    launch()
    return {"accepted": True, "number": ordinal, "bytes": size}


@router.post("/start")
def start(options: StartOptions):
    setup()
    set_setting("ai", "1" if options.use_local_ai else "0")
    set_setting("running", "1")
    launch()
    return status()


@router.post("/pause")
def pause():
    setup()
    set_setting("running", "0")
    return status()


@router.post("/retry")
def retry():
    setup()
    with db() as con:
        updated = con.execute("UPDATE jobs SET state='queued', warnings='[]', "
                              "updated=? WHERE state='failed'", (time(),)).rowcount
    launch()
    return {"requeued": updated}


@router.get("/export")
def export():
    setup()
    if setting("running") == "1":
        raise HTTPException(409, "Verarbeitung vor ZIP-Export pausieren")
    with db() as con:
        if con.execute("SELECT COUNT(*) FROM jobs WHERE state='processing'").fetchone()[0]:
            raise HTTPException(409, "Aktuelle E-Mail wird noch verarbeitet")
        rows = con.execute("SELECT ordinal,id,warnings FROM jobs WHERE state='review' "
                           "ORDER BY ordinal").fetchall()
    if not rows:
        raise HTTPException(404, "Keine anonymisierten E-Mails vorhanden")
    temporary = tempfile.NamedTemporaryFile(prefix="eml-export-", suffix=".zip",
                                            dir=ROOT / "temporary", delete=False)
    path = Path(temporary.name)
    temporary.close()
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=3, allowZip64=True) as z:
            report = []
            for row in rows:
                source = ROOT / "outgoing" / (row["id"] + ".eml")
                if not source.is_file():
                    continue
                name = f"email-{row['ordinal']:06d}.eml"
                z.write(source, name)
                report.append({"file": name, "review_required": True,
                               "warnings": json.loads(row["warnings"])})
            z.writestr("ANONYMIZATION-REVIEW.json",
                       json.dumps(report, ensure_ascii=False, indent=2))
        return FileResponse(path, media_type="application/zip",
                            filename="mlx-nobby-eml-review-required.zip",
                            background=BackgroundTask(lambda: path.unlink(missing_ok=True)),
                            headers={"Cache-Control": "no-store"})
    except Exception:
        path.unlink(missing_ok=True)
        raise


@router.post("/purge")
def purge():
    setup()
    if setting("running") == "1":
        raise HTTPException(409, "Verarbeitung zuerst pausieren")
    with db() as con:
        if con.execute("SELECT COUNT(*) FROM jobs WHERE state='processing'").fetchone()[0]:
            raise HTTPException(409, "Verarbeitung noch nicht abgeschlossen")
        # Disk artifacts first; database is then cleared. Never touch other folders.
        for folder in ("incoming", "outgoing", "temporary"):
            for item in (ROOT / folder).iterdir():
                if item.is_file():
                    item.unlink()
        con.execute("DELETE FROM jobs")
    return {"ok": True}
