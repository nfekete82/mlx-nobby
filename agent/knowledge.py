"""Local SQLite/FTS5 knowledge base backed by the separate embedding service."""
import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path.home() / ".config/mlx-web/knowledge"
DB = ROOT / "knowledge.db"
EMBEDDINGS_URL = os.environ.get("EMBEDDINGS_URL", "http://127.0.0.1:8020").rstrip("/")

EMBEDDINGS_TIMEOUT = float(
    os.environ.get(
        "MLX_EMBEDDING_CLIENT_TIMEOUT",
        "180",
    )
)

EMBEDDING_QUERY_INSTRUCTION = os.environ.get(
    "MLX_EMBEDDING_QUERY_INSTRUCTION",
    (
        "Given a user query, retrieve relevant "
        "source-code and document passages "
        "that answer the query"
    ),
).strip()


def _embedding_query_text(query):
    query = str(query or "").strip()

    if not EMBEDDING_QUERY_INSTRUCTION:
        return query

    return (
        "Instruct: "
        + EMBEDDING_QUERY_INSTRUCTION
        + "\nQuery:"
        + query
    )

IGNORE_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "__pycache__",
    ".venv",
    "venv",
    "agent-venv",
    "image-venv-python313-backup-20260904",
    "backups",
    "dist",
    "build",
    "tmp",
    "temp",
    "cache",
    ".cache",
}
IGNORE_NAMES = {".env", "id_rsa", "id_ed25519"}
TEXT_EXT = {".php", ".py", ".js", ".ts", ".tsx", ".jsx", ".sql", ".md", ".txt", ".json", ".csv", ".html", ".css", ".yml", ".yaml", ".xml"}

def _db():
    ROOT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS knowledge_sources(source_id TEXT PRIMARY KEY,name TEXT NOT NULL,root_path TEXT UNIQUE NOT NULL,created_at REAL,updated_at REAL,last_indexed_at REAL,enabled INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS knowledge_documents(document_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,absolute_path TEXT UNIQUE NOT NULL,relative_path TEXT,filename TEXT,extension TEXT,language TEXT,size INTEGER,mtime REAL,content_hash TEXT,indexed_at REAL,chunk_count INTEGER DEFAULT 0,FOREIGN KEY(source_id) REFERENCES knowledge_sources(source_id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS knowledge_chunks(chunk_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,chunk_index INTEGER,content TEXT,start_line INTEGER,end_line INTEGER,symbol TEXT,symbol_type TEXT,metadata_json TEXT,content_hash TEXT,FOREIGN KEY(document_id) REFERENCES knowledge_documents(document_id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS knowledge_embeddings(chunk_id TEXT PRIMARY KEY,model TEXT,dimensions INTEGER,vector BLOB,created_at REAL,content_hash TEXT,FOREIGN KEY(chunk_id) REFERENCES knowledge_chunks(chunk_id) ON DELETE CASCADE);
    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(chunk_id UNINDEXED, content, filename, path, tokenize='unicode61');
    CREATE TABLE IF NOT EXISTS knowledge_metadata(key TEXT PRIMARY KEY,value TEXT);
    """)
    return con

def _hash(value): return hashlib.sha256(value.encode("utf-8")).hexdigest()
def _language(path):
    return {".py":"python", ".php":"php", ".js":"javascript", ".jsx":"javascript", ".ts":"typescript", ".tsx":"typescript", ".sql":"sql", ".md":"markdown"}.get(path.suffix.lower(), "text")
def _allowed(path):
    n=path.name.lower()
    return path.suffix.lower() in TEXT_EXT and n not in IGNORE_NAMES and not n.endswith((".pem", ".key")) and not n.startswith(("credentials", "secrets"))
def _chunks(text, language):
    lines=text.splitlines(); out=[]; start=0; size=0; symbol=None; symbol_type=None
    marker=re.compile(r"^\s*(?:def|class|function|async function|CREATE\s+TABLE)\s+([\w.]+)|^\s*(#+)\s+(.+)", re.I)
    for idx,line in enumerate(lines):
        match=marker.match(line)
        if match:
            symbol=match.group(1) or match.group(3); symbol_type="heading" if match.group(2) else "symbol"
        size += len(line)+1
        if size >= 1800 and idx > start:
            body="\n".join(lines[start:idx+1]).strip()
            if body: out.append((body,start+1,idx+1,symbol,symbol_type))
            start=max(start,idx-8); size=sum(len(x)+1 for x in lines[start:idx+1])
    body="\n".join(lines[start:]).strip()
    if body: out.append((body,start+1,len(lines),symbol,symbol_type))
    return out or [(text[:1800],1,max(1,len(lines)),None,None)]

def _request(path, payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(EMBEDDINGS_URL+path,data=data,headers={"Content-Type":"application/json"} if data else {},method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=EMBEDDINGS_TIMEOUT) as r: return json.loads(r.read().decode())
def embedding_health():
    try:
        h=_request("/health")
        return h if h.get("ok") else None
    except (urllib.error.URLError, TimeoutError, ValueError): return None

def compatible_embedding_models():
    try:
        return set(_request("/compatible-models")["aliases"])
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return set()
def _pack(v): return struct.pack("<%sf" % len(v), *v)
def _unpack(blob): return struct.unpack("<%sf" % (len(blob)//4), blob)

def index_source(root_path, name=None, force=False):
    root=Path(root_path).expanduser().resolve()
    if not root.is_dir(): raise ValueError("Quelle ist kein lesbares Verzeichnis")
    con=_db(); now=time.time(); sid=_hash(str(root))[:16]; name=name or root.name
    con.execute("INSERT INTO knowledge_sources VALUES(?,?,?,?,?,?,1) ON CONFLICT(root_path) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at,enabled=1",(sid,name,str(root),now,now,None))
    health=embedding_health(); model=(health or {}).get("model"); dimensions=(health or {}).get("dimensions")
    if health: con.execute("INSERT OR REPLACE INTO knowledge_metadata VALUES('embedding_model',?)",(model,)); con.execute("INSERT OR REPLACE INTO knowledge_metadata VALUES('embedding_dimensions',?)",(str(dimensions),))
    seen=set(); changed=[]; skipped=0
    for base,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if d not in IGNORE_DIRS]
        for filename in files:
            path=(Path(base)/filename)
            if not _allowed(path) or path.is_symlink(): continue
            try:
                real=path.resolve(); real.relative_to(root); raw=real.read_text(encoding="utf-8",errors="replace")
            except (OSError, ValueError): continue
            digest=_hash(raw); seen.add(str(real)); stat=real.stat(); old=con.execute("SELECT document_id,content_hash FROM knowledge_documents WHERE absolute_path=?",(str(real),)).fetchone()
            indexed = con.execute("SELECT count(*) FROM knowledge_chunks c JOIN knowledge_embeddings e ON e.chunk_id=c.chunk_id WHERE c.document_id=? AND e.model=? AND e.dimensions=?",(old["document_id"],model,dimensions)).fetchone()[0] if old and health else 0
            chunk_count = con.execute("SELECT count(*) FROM knowledge_chunks WHERE document_id=?",(old["document_id"],)).fetchone()[0] if old else 0
            if old and old["content_hash"]==digest and not force and (not health or indexed == chunk_count): skipped+=1; continue
            did=_hash(str(real))[:24]
            con.execute("DELETE FROM knowledge_fts WHERE chunk_id IN (SELECT chunk_id FROM knowledge_chunks WHERE document_id=?)",(did,))
            con.execute("DELETE FROM knowledge_documents WHERE document_id=?",(did,))
            parts=_chunks(raw,_language(real)); con.execute("INSERT INTO knowledge_documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(did,sid,str(real),str(real.relative_to(root)),real.name,real.suffix.lower(),_language(real),stat.st_size,stat.st_mtime,digest,now,len(parts)))
            for i,(body,a,b,sym,stype) in enumerate(parts):
                cid=_hash(did+str(i))[:24]; ch=_hash(body); meta=json.dumps({"language":_language(real),"symbol":sym,"symbol_type":stype})
                con.execute("INSERT INTO knowledge_chunks VALUES(?,?,?,?,?,?,?,?,?,?)",(cid,did,i,body,a,b,sym,stype,meta,ch)); con.execute("INSERT INTO knowledge_fts VALUES(?,?,?,?)",(cid,body,real.name,str(real.relative_to(root))))
                changed.append((cid,body,ch))
    for row in con.execute("SELECT document_id,absolute_path FROM knowledge_documents WHERE source_id=?",(sid,)).fetchall():
        if row["absolute_path"] not in seen:
            con.execute("DELETE FROM knowledge_fts WHERE chunk_id IN (SELECT chunk_id FROM knowledge_chunks WHERE document_id=?)",(row["document_id"],)); con.execute("DELETE FROM knowledge_documents WHERE document_id=?",(row["document_id"],))
    if health and changed:
        for offset in range(0,len(changed),8):
            group=changed[offset:offset+8]; response=_request("/embeddings",{"texts":[x[1] for x in group]})
            vectors=response["vectors"]
            if response.get("model") != model or response.get("dimensions") != dimensions or len(vectors) != len(group):
                con.close(); raise RuntimeError("Embedding-Modell während der Indexierung gewechselt")
            for (cid,_,ch),vector in zip(group,vectors): con.execute("INSERT OR REPLACE INTO knowledge_embeddings VALUES(?,?,?,?,?,?)",(cid,model,dimensions,_pack(vector),now,ch))
    con.execute("UPDATE knowledge_sources SET last_indexed_at=?,updated_at=? WHERE source_id=?",(now,now,sid)); con.commit(); con.close()
    return {"source_id":sid,"name":name,"indexed":len(changed),"skipped":skipped,"mode":"hybrid" if health else "fts_fallback"}

def status():
    con=_db(); sources=[dict(r) for r in con.execute("SELECT source_id,name,root_path,last_indexed_at,enabled FROM knowledge_sources ORDER BY name")]; docs=con.execute("SELECT count(*) FROM knowledge_documents").fetchone()[0]; chunks=con.execute("SELECT count(*) FROM knowledge_chunks").fetchone()[0]; con.close()
    return {"sources":sources,"documents":docs,"chunks":chunks,"embedding":embedding_health(),"mode":"hybrid" if embedding_health() else "fts_fallback"}

def _fts_query(query):
    terms = re.findall(r"\w+", str(query or ""), flags=re.UNICODE)
    terms = [term for term in terms if len(term) >= 2]

    if not terms:
        return ""

    quoted = [
        f'"{term.replace(chr(34), chr(34) * 2)}"'
        for term in terms
    ]

    return " OR ".join(quoted)


def search(query, scope=None, limit=6):
    con = _db()
    fts_query = _fts_query(query)

    fts = []
    if fts_query:
        try:
            params = [fts_query]
            where = ""

            where = " AND s.enabled=1"

            if scope:
                where += " AND s.name LIKE ?"
                params.append("%" + scope + "%")

            fts = con.execute(
                "SELECT "
                "c.chunk_id,c.content,c.start_line,c.end_line,c.symbol,"
                "d.relative_path,s.name "
                "FROM knowledge_fts f "
                "JOIN knowledge_chunks c ON c.chunk_id=f.chunk_id "
                "JOIN knowledge_documents d ON d.document_id=c.document_id "
                "JOIN knowledge_sources s ON s.source_id=d.source_id "
                "WHERE knowledge_fts MATCH ?"
                + where +
                " ORDER BY bm25(knowledge_fts) LIMIT 12",
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            fts = []

    mode = "fts_fallback"
    ranked = {
        r["chunk_id"]: (i + 1, r)
        for i, r in enumerate(fts)
    }

    health = embedding_health()
    sims = []
    similarity_by_id = {}

    if health:
        try:
            embedded_query = _request(
                "/embedding",
                {"text": _embedding_query_text(query)},
            )
            q = embedded_query["vectors"][0]

            rows = con.execute(
                "SELECT "
                "c.chunk_id,c.content,c.start_line,c.end_line,c.symbol,"
                "d.relative_path,s.name,e.vector "
                "FROM knowledge_embeddings e "
                "JOIN knowledge_chunks c ON c.chunk_id=e.chunk_id "
                "JOIN knowledge_documents d ON d.document_id=c.document_id "
                "JOIN knowledge_sources s ON s.source_id=d.source_id "
                "WHERE s.enabled=1 AND e.model=? AND e.dimensions=?"
                + (" AND s.name LIKE ?" if scope else ""),
                [embedded_query["model"], embedded_query["dimensions"], *(["%" + scope + "%"] if scope else [])],
            ).fetchall()

            sims = sorted(
                (
                    (
                        sum(
                            a * b
                            for a, b in zip(
                                q,
                                _unpack(r["vector"]),
                            )
                        ),
                        r,
                    )
                    for r in rows
                ),
                reverse=True,
                key=lambda x: x[0],
            )[:12]

            for similarity, r in sims:
                similarity_by_id[r["chunk_id"]] = float(similarity)

            scores = {}

            for i, r in enumerate(fts):
                scores[r["chunk_id"]] = (
                    scores.get(r["chunk_id"], 0)
                    + 1 / (60 + i + 1)
                )

            for i, (_, r) in enumerate(sims):
                scores[r["chunk_id"]] = (
                    scores.get(r["chunk_id"], 0)
                    + 1 / (60 + i + 1)
                )
                ranked.setdefault(
                    r["chunk_id"],
                    (999, r),
                )

            ordered = sorted(
                (ranked[k][1] for k in scores),
                key=lambda r: scores[r["chunk_id"]],
                reverse=True,
            )

            mode = "hybrid" if fts else "vector"

        except Exception:
            ordered = list(fts)

    else:
        ordered = list(fts)

    results = [
        {
            "source": r["name"],
            "path": r["relative_path"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "symbol": r["symbol"],
            "snippet": r["content"][:700],
            "similarity": similarity_by_id.get(r["chunk_id"]),
        }
        for r in ordered[:limit]
    ]

    con.close()

    return {
        "mode": mode,
        "query": query,
        "scope": scope,
        "results": results,
    }


# ============================================================
# Uploaded document RAG
# ============================================================

def _ensure_uploaded_document_tables(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS uploaded_documents(
        document_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        document_type TEXT NOT NULL,
        page_count INTEGER DEFAULT 0,
        created_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS uploaded_document_chunks(
        chunk_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        page INTEGER NOT NULL,
        chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL,
        vector BLOB,
        dimensions INTEGER,
        model TEXT,
        FOREIGN KEY(document_id)
            REFERENCES uploaded_documents(document_id)
            ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_uploaded_chunks_document
        ON uploaded_document_chunks(document_id);

    CREATE INDEX IF NOT EXISTS idx_uploaded_chunks_page
        ON uploaded_document_chunks(document_id, page);
    """)


def _document_text_chunks(text, target_chars=1800, overlap_chars=250):
    text = str(text or "").strip()

    if not text:
        return []

    if len(text) <= target_chars:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = min(
            len(text),
            start + target_chars,
        )

        if end < len(text):
            boundary = max(
                text.rfind("\n", start, end),
                text.rfind(". ", start, end),
            )

            if boundary > start + target_chars // 2:
                end = boundary + 1

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(
            start + 1,
            end - overlap_chars,
        )

    return chunks


def index_uploaded_document(
    document_id,
    name,
    pages,
    document_type="pdf",
    progress_callback=None,
):
    document_id = str(document_id or "").strip()
    name = str(name or "").strip()

    if not document_id:
        raise ValueError("document_id fehlt")

    if not name:
        raise ValueError("Dokumentname fehlt")

    if not isinstance(pages, list):
        raise ValueError("pages muss eine Liste sein")

    health = embedding_health()

    if not health:
        raise RuntimeError(
            "Embedding-Service ist nicht erreichbar"
        )

    model = health["model"]
    dimensions = int(health["dimensions"])

    prepared = []

    for page_item in pages:
        if not isinstance(page_item, dict):
            continue

        try:
            page_number = int(page_item.get("page"))
        except (TypeError, ValueError):
            continue

        text = str(page_item.get("text") or "").strip()

        if not text:
            continue

        for chunk_index, body in enumerate(
            _document_text_chunks(text)
        ):
            prepared.append({
                "page": page_number,
                "chunk_index": chunk_index,
                "content": body,
            })

    con = _db()
    _ensure_uploaded_document_tables(con)

    # Reuse a fully indexed document. document_id is based on the SHA-256
    # of the original file and is therefore stable for identical PDFs.
    existing = con.execute(
        """
        SELECT
            d.document_id,
            d.name,
            d.document_type,
            d.page_count,
            d.created_at,
            COUNT(c.chunk_id) AS chunk_count,
            MAX(c.model) AS model,
            MAX(c.dimensions) AS dimensions
        FROM uploaded_documents d
        LEFT JOIN uploaded_document_chunks c
            ON c.document_id = d.document_id
        WHERE d.document_id = ?
        GROUP BY
            d.document_id,
            d.name,
            d.document_type,
            d.page_count,
            d.created_at
        """,
        (document_id,),
    ).fetchone()

    if (
        existing
        and int(existing["chunk_count"] or 0) > 0
        and int(existing["page_count"] or 0) == len(pages)
        and existing["model"] == model
        and int(existing["dimensions"] or 0) == dimensions
    ):
        result = {
            "document_id": document_id,
            "name": name,
            "pages": int(existing["page_count"]),
            "chunks": int(existing["chunk_count"]),
            "model": existing["model"],
            "dimensions": int(existing["dimensions"]),
            "indexed_at": existing["created_at"],
            "cached": True,
        }

        con.close()
        return result

    con.execute(
        "DELETE FROM uploaded_documents WHERE document_id=?",
        (document_id,),
    )

    con.execute(
        """
        INSERT INTO uploaded_documents(
            document_id,
            name,
            document_type,
            page_count,
            created_at
        )
        VALUES(?,?,?,?,?)
        """,
        (
            document_id,
            name,
            document_type,
            len(pages),
            time.time(),
        ),
    )

    now = time.time()

    total_chunks = len(prepared)

    if progress_callback:
        progress_callback(0, total_chunks)

    for offset in range(0, total_chunks, 8):
        group = prepared[offset:offset + 8]

        response = _request(
            "/embeddings",
            {
                "texts": [
                    item["content"]
                    for item in group
                ]
            },
        )

        vectors = response["vectors"]
        if response.get("model") != model or response.get("dimensions") != dimensions or len(vectors) != len(group):
            con.close()
            raise RuntimeError("Embedding-Modell während der Indexierung gewechselt")

        for item, vector in zip(group, vectors):
            chunk_id = _hash(
                document_id +
                ":" +
                str(item["page"]) +
                ":" +
                str(item["chunk_index"])
            )[:24]

            con.execute(
                """
                INSERT INTO uploaded_document_chunks(
                    chunk_id,
                    document_id,
                    page,
                    chunk_index,
                    content,
                    vector,
                    dimensions,
                    model
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    chunk_id,
                    document_id,
                    item["page"],
                    item["chunk_index"],
                    item["content"],
                    _pack(vector),
                    dimensions,
                    model,
                ),
            )

        if progress_callback:
            progress_callback(
                min(offset + len(group), total_chunks),
                total_chunks,
            )

    con.commit()
    con.close()

    return {
        "document_id": document_id,
        "name": name,
        "pages": len(pages),
        "chunks": len(prepared),
        "model": model,
        "dimensions": dimensions,
        "indexed_at": now,
    }


def get_uploaded_document_page(document_id, page):
    document_id = str(document_id or "").strip()

    if not document_id:
        raise ValueError("document_id fehlt")

    try:
        page = int(page)
    except (TypeError, ValueError):
        raise ValueError("Ungültige Seitennummer")

    if page < 1:
        raise ValueError("Seitennummer muss mindestens 1 sein")

    con = _db()
    _ensure_uploaded_document_tables(con)

    document = con.execute(
        """
        SELECT
            document_id,
            name,
            document_type,
            page_count
        FROM uploaded_documents
        WHERE document_id=?
        """,
        (document_id,),
    ).fetchone()

    if not document:
        con.close()
        raise ValueError("Dokument nicht gefunden")

    if page > int(document["page_count"] or 0):
        con.close()
        raise ValueError(
            f"Seite {page} liegt außerhalb des Dokuments "
            f"({document['page_count']} Seiten)"
        )

    rows = con.execute(
        """
        SELECT
            chunk_index,
            content
        FROM uploaded_document_chunks
        WHERE document_id=?
          AND page=?
        ORDER BY chunk_index ASC
        """,
        (document_id, page),
    ).fetchall()

    con.close()

    if not rows:
        return {
            "document_id": document_id,
            "name": document["name"],
            "document_type": document["document_type"],
            "page": page,
            "page_count": int(document["page_count"] or 0),
            "chunks": 0,
            "text": "",
        }

    parts = []

    for row in rows:
        text = str(row["content"] or "")

        if not text:
            continue

        if not parts:
            parts.append(text)
            continue

        previous = parts[-1]

        # Index chunks overlap. Remove the largest identical suffix/prefix
        # region so page text is not reconstructed twice.
        max_overlap = min(
            250,
            len(previous),
            len(text),
        )

        overlap = 0

        for size in range(max_overlap, 0, -1):
            if previous[-size:] == text[:size]:
                overlap = size
                break

        parts.append(text[overlap:])

    return {
        "document_id": document_id,
        "name": document["name"],
        "document_type": document["document_type"],
        "page": page,
        "page_count": int(document["page_count"] or 0),
        "chunks": len(rows),
        "text": "".join(parts),
    }


def search_uploaded_document(
    document_id,
    query,
    limit=6,
):
    document_id = str(document_id or "").strip()
    query = str(query or "").strip()

    if not document_id:
        raise ValueError("document_id fehlt")

    if not query:
        raise ValueError("Suchanfrage fehlt")

    embedded_query = _request(
        "/embedding",
        {"text": _embedding_query_text(query)},
    )
    q = embedded_query["vectors"][0]

    con = _db()
    _ensure_uploaded_document_tables(con)

    rows = con.execute(
        """
        SELECT
            chunk_id,
            page,
            chunk_index,
            content,
            vector
        FROM uploaded_document_chunks
        WHERE document_id=?
          AND vector IS NOT NULL
          AND model=?
          AND dimensions=?
        """,
        (document_id, embedded_query["model"], embedded_query["dimensions"]),
    ).fetchall()

    ranked = []

    for row in rows:
        vector = _unpack(row["vector"])

        similarity = sum(
            a * b
            for a, b in zip(q, vector)
        )

        ranked.append(
            (
                similarity,
                row,
            )
        )

    ranked.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    results = []

    for score, row in ranked[:max(1, int(limit))]:
        results.append({
            "page": row["page"],
            "chunk_index": row["chunk_index"],
            "score": float(score),
            "content": row["content"],
        })

    con.close()

    return {
        "document_id": document_id,
        "query": query,
        "results": results,
    }

def get_source(source_id):
    source_id = str(source_id or "").strip()
    if not source_id:
        raise ValueError("source_id fehlt")

    con = _db()
    row = con.execute(
        """
        SELECT source_id,name,root_path,created_at,updated_at,
               last_indexed_at,enabled
        FROM knowledge_sources
        WHERE source_id=?
        """,
        (source_id,),
    ).fetchone()
    con.close()

    if not row:
        raise ValueError("Wissensquelle nicht gefunden")

    return dict(row)


def set_source_enabled(source_id, enabled):
    source = get_source(source_id)

    con = _db()
    con.execute(
        """
        UPDATE knowledge_sources
        SET enabled=?,updated_at=?
        WHERE source_id=?
        """,
        (
            1 if enabled else 0,
            time.time(),
            source_id,
        ),
    )
    con.commit()
    con.close()

    source["enabled"] = 1 if enabled else 0
    return source


def reindex_source(source_id):
    source = get_source(source_id)

    result = index_source(
        source["root_path"],
        source["name"],
        True,
    )

    if not source["enabled"]:
        set_source_enabled(source_id, False)

    return result


def delete_source(source_id):
    source = get_source(source_id)

    con = _db()

    chunk_rows = con.execute(
        """
        SELECT c.chunk_id
        FROM knowledge_chunks c
        JOIN knowledge_documents d
          ON d.document_id=c.document_id
        WHERE d.source_id=?
        """,
        (source_id,),
    ).fetchall()

    chunk_ids = [
        row["chunk_id"]
        for row in chunk_rows
    ]

    if chunk_ids:
        con.executemany(
            "DELETE FROM knowledge_fts WHERE chunk_id=?",
            [(chunk_id,) for chunk_id in chunk_ids],
        )

    con.execute(
        "DELETE FROM knowledge_sources WHERE source_id=?",
        (source_id,),
    )

    con.commit()
    con.close()

    return {
        "deleted": True,
        "source_id": source_id,
        "name": source["name"],
        "root_path": source["root_path"],
    }
