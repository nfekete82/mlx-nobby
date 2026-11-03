"""Bounded local Office/ZIP inspection and exact-string edits.

Office files are data, never executable code. All edits write a *new* copy.
Legacy .xls and .doc cannot be rewritten by this implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

from docx import Document
from openpyxl import load_workbook
import xlrd


MAX_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_UNPACKED = 40 * 1024 * 1024
MAX_ARCHIVE_ITEMS = 120
MAX_PREVIEW_CHARS = 14000
MAX_REPLACEMENTS = 32
MAX_LEGACY_DOC_TEXT_BYTES = 512 * 1024
LEGACY_DOC_TIMEOUT_SECONDS = 12
ZIP_TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".xml", ".html", ".css", ".js", ".py", ".sql", ".yaml", ".yml"}
SUPPORTED = {".doc", ".docx", ".xlsx", ".xls", ".zip", ".csv", ".txt", ".md", ".json"}
EDITABLE = {".docx", ".xlsx", ".zip", ".csv", ".txt", ".md", ".json"}


class OfficeError(ValueError):
    pass


@dataclass
class Inspection:
    kind: str
    preview: str
    files: int
    cells: int = 0
    paragraphs: int = 0
    truncated: bool = False


def extension(filename: str) -> str:
    value = str(filename or "").lower().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    suffix = "." + value.rsplit(".", 1)[-1] if "." in value else ""
    if suffix not in SUPPORTED:
        raise OfficeError("UNSUPPORTED_FILE_TYPE")
    return suffix


def _preview(parts, kind, files=1, cells=0, paragraphs=0):
    text = "\n".join(parts)
    return Inspection(
        kind=kind, preview=text[:MAX_PREVIEW_CHARS], files=files,
        cells=cells, paragraphs=paragraphs, truncated=len(text) > MAX_PREVIEW_CHARS,
    )


def _zip_entries(zf: zipfile.ZipFile):
    items = zf.infolist()
    if len(items) > MAX_ARCHIVE_ITEMS:
        raise OfficeError("ZIP_TOO_MANY_ENTRIES")
    size = 0
    result = []
    seen = set()
    for info in items:
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if (not name or name.startswith("/") or "\x00" in name
                or ".." in path.parts or not path.parts
                or ":" in path.parts[0] or len(name) > 350):
            raise OfficeError("UNSAFE_ZIP_PATH")
        if name in seen:
            raise OfficeError("ZIP_DUPLICATE_PATH")
        seen.add(name)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise OfficeError("ZIP_SYMLINK_BLOCKED")
        if info.flag_bits & 1:
            raise OfficeError("ENCRYPTED_ZIP_UNSUPPORTED")
        if info.is_dir():
            continue
        size += info.file_size
        if size > MAX_ARCHIVE_UNPACKED:
            raise OfficeError("ZIP_TOO_LARGE")
        if info.file_size > 8 * 1024 * 1024:
            raise OfficeError("ZIP_MEMBER_TOO_LARGE")
        if info.compress_size and info.file_size > info.compress_size * 150:
            raise OfficeError("ZIP_SUSPICIOUS_RATIO")
        result.append(info)
    return result


def _document_parts(doc):
    result = []
    for p in doc.paragraphs:
        if p.text.strip():
            result.append(p.text)
    for index, table in enumerate(doc.tables, 1):
        result.append(f"[Table {index}]")
        for row in table.rows:
            result.append(" | ".join(cell.text[:700] for cell in row.cells))
    return result



def _inspect_legacy_doc(data: bytes) -> Inspection:
    """Extract plain text from an OLE Word 97-2003 document, without macros."""
    if not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise OfficeError("INVALID_OR_UNREADABLE_DOCUMENT")
    reader = shutil.which("antiword")
    if not reader:
        raise OfficeError("DOC_READER_UNAVAILABLE")
    # Keep extracted text in an anonymous temporary file rather than memory
    # or logs. Never execute a shell or interpret embedded Word macros.
    env = dict(os.environ)
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    try:
        with tempfile.TemporaryFile(mode="w+b") as output:
            finished = subprocess.run(
                [reader, "-m", "UTF-8.txt", "-w", "0", "-"],
                input=data,
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=LEGACY_DOC_TIMEOUT_SECONDS,
                check=False,
                env=env,
            )
            if finished.returncode != 0 or output.tell() > MAX_LEGACY_DOC_TEXT_BYTES:
                raise OfficeError("INVALID_OR_UNREADABLE_DOCUMENT")
            output.seek(0)
            text = output.read(MAX_LEGACY_DOC_TEXT_BYTES + 1).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise OfficeError("DOC_READER_TIMEOUT") from exc
    except OSError as exc:
        raise OfficeError("DOC_READER_FAILED") from exc
    if not text.strip():
        raise OfficeError("INVALID_OR_UNREADABLE_DOCUMENT")
    paragraphs = sum(bool(line.strip()) for line in text.splitlines())
    return _preview([text], "doc", paragraphs=paragraphs)

def inspect(data: bytes, filename: str) -> Inspection:
    suffix = extension(filename)
    if not data or len(data) > MAX_BYTES:
        raise OfficeError("FILE_EMPTY_OR_TOO_LARGE")
    try:
        if suffix == ".doc":
            return _inspect_legacy_doc(data)
        if suffix in {".docx", ".xlsx"}:
            # Office Open XML is a ZIP container; apply the same bounded
            # member and decompression checks before passing it to a parser.
            with zipfile.ZipFile(BytesIO(data)) as zipped:
                _zip_entries(zipped)
        if suffix == ".docx":
            doc = Document(BytesIO(data))
            parts = _document_parts(doc)
            return _preview(parts, "docx", paragraphs=len(doc.paragraphs))
        if suffix == ".xlsx":
            book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
            parts, cell_count = [], 0
            try:
                for sheet in book:
                    parts.append(f"[Sheet: {sheet.title}]")
                    for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 500),
                                                   min_col=1, max_col=min(sheet.max_column, 60)):
                        nonempty = [f"{cell.coordinate}={str(cell.value)[:300]}" for cell in row if cell.value is not None]
                        cell_count += len(nonempty)
                        if nonempty:
                            parts.append(" | ".join(nonempty[:24]))
                        if sum(len(x) for x in parts) > MAX_PREVIEW_CHARS * 2:
                            break
            finally:
                book.close()
            return _preview(parts, "xlsx", cells=cell_count)
        if suffix == ".xls":
            book = xlrd.open_workbook(file_contents=data)
            parts, count = [], 0
            for sheet in book.sheets():
                parts.append(f"[Sheet: {sheet.name}]")
                for i in range(min(sheet.nrows, 500)):
                    cells = [f"R{i+1}C{j+1}={str(sheet.cell_value(i,j))[:300]}"
                             for j in range(min(sheet.ncols, 24)) if sheet.cell_value(i,j) != ""]
                    count += len(cells)
                    if cells:
                        parts.append(" | ".join(cells))
            return _preview(parts, "xls", cells=count)
        if suffix == ".zip":
            with zipfile.ZipFile(BytesIO(data)) as zf:
                entries = _zip_entries(zf)
                parts = [f"[Archive: {len(entries)} files]"]
                for item in entries:
                    p = PurePosixPath(item.filename)
                    parts.append(f"[{p.as_posix()} — {item.file_size} bytes]")
                    if p.suffix.lower() in ZIP_TEXT_EXTS and item.file_size < 512 * 1024:
                        raw = zf.read(item)
                        parts.append(raw.decode("utf-8", errors="replace")[:1200])
                    if sum(map(len, parts)) > MAX_PREVIEW_CHARS * 2:
                        break
                return _preview(parts, "zip", files=len(entries))
        raw = data.decode("utf-8-sig")
        return _preview([raw], suffix.lstrip("."))
    except OfficeError:
        raise
    except (ValueError, UnicodeError, OSError, zipfile.BadZipFile, KeyError, RuntimeError, TypeError) as exc:
        raise OfficeError("INVALID_OR_UNREADABLE_DOCUMENT") from exc


def validated_replacements(value):
    if not isinstance(value, list) or len(value) > MAX_REPLACEMENTS:
        raise OfficeError("INVALID_EDIT_PLAN")
    replacements = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise OfficeError("INVALID_EDIT_PLAN")
        old, new = item.get("old"), item.get("new")
        if (not isinstance(old, str) or not old or len(old) > 400
                or not isinstance(new, str) or len(new) > 1200):
            raise OfficeError("INVALID_EDIT_PLAN")
        if old in seen:
            raise OfficeError("DUPLICATE_EDIT")
        seen.add(old)
        replacements.append((old, new))
    return replacements


def _replace_text(text, rules):
    edits = 0
    for old, new in rules:
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            edits += count
    return text, edits


def _docx_edit(data, rules):
    doc = Document(BytesIO(data))
    count = 0
    paragraphs = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    for paragraph in paragraphs:
        # Preserve run styling when the replacement fits one run.
        for run in paragraph.runs:
            modified, changed = _replace_text(run.text, rules)
            if changed:
                run.text = modified
                count += changed
        # Cross-run phrases are intentionally not rewritten: doing so would
        # silently discard mixed formatting and hyperlinks.
    result = BytesIO()
    doc.save(result)
    return result.getvalue(), count


def _xlsx_edit(data, rules):
    book = load_workbook(BytesIO(data), keep_links=False)
    changes = 0
    for sheet in book:
        for row in sheet:
            for cell in row:
                if cell.data_type == "f" or not isinstance(cell.value, str):
                    continue
                modified, count = _replace_text(cell.value, rules)
                if count:
                    if modified.lstrip().startswith("="):
                        raise OfficeError("FORMULA_INJECTION_BLOCKED")
                    cell.value = modified
                    changes += count
    output = BytesIO()
    book.save(output)
    return output.getvalue(), changes


def _zip_edit(data, rules):
    updates = 0
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as source:
        entries = _zip_entries(source)
        with zipfile.ZipFile(out, "w") as target:
            for item in source.infolist():
                if item.is_dir():
                    target.writestr(item, b"")
                    continue
                original = source.read(item)
                ext = PurePosixPath(item.filename).suffix.lower()
                changed = 0
                if ext in ZIP_TEXT_EXTS:
                    try:
                        decoded = original.decode("utf-8-sig")
                        new_text, changed = _replace_text(decoded, rules)
                        if changed:
                            original = new_text.encode("utf-8")
                    except UnicodeDecodeError:
                        pass
                updates += changed
                # Copy member metadata and unrelated bytes unchanged.
                target.writestr(item, original)
    if len(out.getvalue()) > MAX_BYTES:
        raise OfficeError("OUTPUT_TOO_LARGE")
    return out.getvalue(), updates


def edit(data: bytes, filename: str, replacements):
    suffix = extension(filename)
    if suffix not in EDITABLE:
        raise OfficeError("READ_ONLY_FORMAT")
    if len(data) > MAX_BYTES or not data:
        raise OfficeError("FILE_EMPTY_OR_TOO_LARGE")
    if suffix in {".docx", ".xlsx"}:
        with zipfile.ZipFile(BytesIO(data)) as zipped:
            _zip_entries(zipped)
    rules = validated_replacements(replacements)
    if not rules:
        raise OfficeError("NO_EDIT_RULES")
    # Only exact content replacements; no arbitrary code, formulas or macros.
    if suffix == ".docx":
        output, count = _docx_edit(data, rules)
    elif suffix == ".xlsx":
        output, count = _xlsx_edit(data, rules)
    elif suffix == ".zip":
        output, count = _zip_edit(data, rules)
    else:
        output_text, count = _replace_text(data.decode("utf-8-sig"), rules)
        output = output_text.encode("utf-8")
    if not count:
        raise OfficeError("EDIT_TEXT_NOT_FOUND")
    if len(output) > MAX_BYTES:
        raise OfficeError("OUTPUT_TOO_LARGE")
    return output, count
