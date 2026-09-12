"""Pure helpers for batch file processing.

This module has no service state and performs no network requests.
"""

import hashlib
import json


BATCH_SINGLE_CHUNK_TOKENS = 12000
BATCH_LARGE_FILE_TOKENS = 64000
BATCH_LARGE_CHUNK_TOKENS = 8000
BATCH_MAX_OUTPUT_TOKENS = 16000
JSON_FREETEXT_BATCH_MAX_ITEMS = 25
JSON_FREETEXT_BATCH_MAX_TOKENS = 3000


def estimate_batch_tokens(text):
    """Estimate tokens without loading a model-specific tokenizer."""
    value = str(text or "")
    if not value:
        return 0
    return max(1, (len(value) + 3) // 4)


def recommended_batch_chunk_tokens(estimated_tokens):
    """Prefer one request for small files and bounded chunks for larger ones."""
    estimated = max(0, int(estimated_tokens or 0))
    if estimated <= BATCH_SINGLE_CHUNK_TOKENS:
        return max(2000, estimated)
    if estimated <= BATCH_LARGE_FILE_TOKENS:
        return BATCH_SINGLE_CHUNK_TOKENS
    return BATCH_LARGE_CHUNK_TOKENS


def batch_max_output_tokens(estimated_input_tokens):
    """Allow structure-preserving transforms to return the complete chunk."""
    estimated = max(1, int(estimated_input_tokens or 1))
    return max(
        384,
        min(
            BATCH_MAX_OUTPUT_TOKENS,
            int(estimated * 1.35) + 256,
        ),
    )


def decode_batch_bytes(raw, encoding, errors="strict"):
    """Decode known input encodings while consuming, not exposing, their BOM."""
    if encoding == "utf-16-le":
        payload = raw[2:] if raw.startswith(b"\xff\xfe") else raw
        return payload.decode("utf-16-le", errors=errors)
    if encoding == "utf-16-be":
        payload = raw[2:] if raw.startswith(b"\xfe\xff") else raw
        return payload.decode("utf-16-be", errors=errors)
    if encoding == "utf-8-sig":
        return raw.decode("utf-8-sig", errors=errors)
    return raw.decode("utf-8", errors=errors)


def write_batch_text(path, text, encoding):
    """Write transformed text atomically and preserve an existing BOM."""
    value = str(text or "")
    if encoding == "utf-8-sig":
        payload = b"\xef\xbb\xbf" + value.encode("utf-8")
    elif encoding == "utf-16-le":
        payload = b"\xff\xfe" + value.encode("utf-16-le")
    elif encoding == "utf-16-be":
        payload = b"\xfe\xff" + value.encode("utf-16-be")
    else:
        payload = value.encode("utf-8")
    path.write_bytes(payload)


def split_batch_content(text, file_type, chunk_size):
    text = str(text or "")
    file_type = str(file_type or "auto").lower()

    def estimate_tokens(value):
        return estimate_batch_tokens(value)

    def pack_units(units):
        chunks = []
        current = ""

        for unit in units:
            if not unit:
                continue

            unit_tokens = estimate_tokens(unit)

            current_tokens = estimate_tokens(current)

            # A single item exceeds the token limit:
            # split it as a final safety measure.
            if unit_tokens > chunk_size:
                if current:
                    chunks.append(current)
                    current = ""

                hard_parts = split_chunk_hard(
                    unit,
                    chunk_size,
                )

                chunks.extend(
                    hard_parts
                )

                continue

            if (
                current and
                current_tokens + unit_tokens > chunk_size
            ):
                chunks.append(current)
                current = ""

            current += unit

        if current:
            chunks.append(current)

        return chunks

    def detect_type():
        stripped = text.lstrip()

        if file_type != "auto":
            return file_type

        if stripped.startswith("{") or stripped.startswith("["):
            return "json"

        upper = stripped[:500].upper()

        if any(
            keyword in upper
            for keyword in (
                "INSERT INTO",
                "UPDATE ",
                "DELETE FROM",
                "CREATE TABLE",
                "ALTER TABLE",
                "SELECT ",
            )
        ):
            return "sql"

        first_line = text.splitlines()[0] if text.splitlines() else ""

        if first_line.count(",") >= 2:
            return "csv"

        return "text"

    detected_type = detect_type()

    # --------------------------------------------------------
    # SQL
    # --------------------------------------------------------
    if detected_type == "sql":
        units = []
        current = []
        in_single_quote = False
        in_double_quote = False
        escaped = False

        for char in text:
            current.append(char)

            if escaped:
                escaped = False
                continue

            if char == "\\":
                escaped = True
                continue

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                continue

            if (
                char == ";"
                and not in_single_quote
                and not in_double_quote
            ):
                unit = "".join(current)

                if unit.strip():
                    units.append(unit)

                current = []

        if current:
            tail = "".join(current)

            if tail.strip():
                units.append(tail)

        return pack_units(units)

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------
    if detected_type == "csv":
        lines = text.splitlines(keepends=True)

        return pack_units(lines)

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------
    if detected_type == "json":
        try:
            data = json.loads(text)

            # Top-level array:
            # each chunk must be valid JSON on its own.
            if isinstance(data, list):
                if not data:
                    return ["[]"]

                chunks = []
                current_items = []

                def serialize_array(items):
                    return json.dumps(
                        items,
                        ensure_ascii=False,
                        indent=2,
                    )

                for item in data:
                    single = serialize_array([item])
                    single_tokens = estimate_tokens(single)

                    # A single oversized element remains valid JSON. Splitting
                    # inside it would corrupt strings or object structure.
                    if single_tokens > chunk_size:
                        if current_items:
                            chunks.append(
                                serialize_array(current_items)
                            )
                            current_items = []

                        chunks.append(single)

                        continue

                    candidate_items = current_items + [item]
                    candidate = serialize_array(candidate_items)

                    if (
                        current_items and
                        estimate_tokens(candidate) > chunk_size
                    ):
                        chunks.append(
                            serialize_array(current_items)
                        )

                        current_items = [item]
                    else:
                        current_items = candidate_items

                if current_items:
                    chunks.append(
                        serialize_array(current_items)
                    )

                return chunks

            serialized = json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            )

            if not isinstance(data, dict) or estimate_tokens(serialized) <= chunk_size:
                return [serialized]

            list_keys = [
                key
                for key, value in data.items()
                if isinstance(value, list) and value
            ]
            if not list_keys:
                return [serialized]

            list_key = max(list_keys, key=lambda key: len(data[key]))
            static_fields = {
                key: value
                for key, value in data.items()
                if key != list_key
            }
            chunks = []
            current_items = []

            def serialize_object(items, include_static):
                payload = dict(static_fields) if include_static else {}
                payload[list_key] = items
                return json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                )

            for item in data[list_key]:
                include_static = not chunks
                candidate_items = current_items + [item]
                candidate = serialize_object(candidate_items, include_static)

                if current_items and estimate_tokens(candidate) > chunk_size:
                    chunks.append(
                        serialize_object(current_items, include_static)
                    )
                    current_items = [item]
                else:
                    current_items = candidate_items

                single = serialize_object(current_items, not chunks)
                if len(current_items) == 1 and estimate_tokens(single) > chunk_size:
                    chunks.append(single)
                    current_items = []

            if current_items:
                chunks.append(
                    serialize_object(current_items, not chunks)
                )

            return chunks

        except json.JSONDecodeError:
            raise ValueError("INVALID_JSON_FOR_CHUNKING")

    # --------------------------------------------------------
    # Text
    # --------------------------------------------------------
    if detected_type == "text":
        # Preserve paragraphs.
        paragraphs = []
        current = []

        for line in text.splitlines(keepends=True):
            current.append(line)

            if not line.strip():
                paragraph = "".join(current)

                if paragraph:
                    paragraphs.append(paragraph)

                current = []

        if current:
            paragraph = "".join(current)

            if paragraph:
                paragraphs.append(paragraph)

        if not paragraphs:
            return [text] if text else []

        return pack_units(paragraphs)

    # Fallback
    return [text] if text else []


def split_chunk_hard(text, max_tokens):
    text = str(text or "")

    max_chars = max(
        400,
        int(max_tokens) * 4,
    )

    if len(text) <= max_chars:
        return [text]

    parts = []
    start = 0

    while start < len(text):
        end = min(
            len(text),
            start + max_chars,
        )

        # Prefer splitting at a line break.
        if end < len(text):
            newline = text.rfind(
                "\n",
                start,
                end,
            )

            if newline > start:
                end = newline + 1

        if end <= start:
            end = min(
                len(text),
                start + max_chars,
            )

        parts.append(
            text[start:end]
        )

        start = end

    return parts


def build_json_freetext_batches(
    targets,
    *,
    max_items=JSON_FREETEXT_BATCH_MAX_ITEMS,
    max_tokens=JSON_FREETEXT_BATCH_MAX_TOKENS,
):
    """Pack free-text targets into small semantic LLM batches."""
    batches = []
    current = []
    current_tokens = 0

    for target in targets:
        text_value = str(target.get("text") or "")

        item_tokens = max(
            1,
            estimate_batch_tokens(text_value),
        )

        if (
            current
            and (
                len(current) >= int(max_items)
                or current_tokens + item_tokens > int(max_tokens)
            )
        ):
            batches.append(current)
            current = []
            current_tokens = 0

        current.append(target)
        current_tokens += item_tokens

    if current:
        batches.append(current)

    return batches


def split_batch_part_for_oom(text, file_type, max_tokens):
    """Retry smaller while keeping JSON fragments independently valid."""
    if str(file_type or "").lower() == "json":
        return split_batch_content(text, "json", max_tokens)
    return split_chunk_hard(text, max_tokens)


def assemble_batch_json(checkpoint_texts, analysis):
    parsed_chunks = [
        json.loads(item)
        for item in checkpoint_texts
    ]
    if not parsed_chunks:
        raise RuntimeError(
            "JSON-Ausgabe enthält keine vollständig verarbeiteten Chunks"
        )

    strategy = analysis.get("chunk_strategy")
    if strategy == "json_array":
        if not all(isinstance(part, list) for part in parsed_chunks):
            raise RuntimeError(
                "JSON-Array-Ausgabe enthält einen ungültigen Chunk"
            )
        value = [
            entry
            for part in parsed_chunks
            for entry in part
        ]
    elif strategy == "json_object_list":
        list_key = analysis.get("json_list_key")
        if not list_key:
            raise RuntimeError(
                "JSON-Listenfeld für Reassembly fehlt"
            )
        value = None
        collected = []
        for index, part in enumerate(parsed_chunks):
            if not isinstance(part, dict) or not isinstance(part.get(list_key), list):
                raise RuntimeError(
                    "JSON-Objekt-Ausgabe enthält einen ungültigen Listen-Chunk"
                )
            if index == 0:
                value = dict(part)
            elif set(part) != {list_key}:
                raise RuntimeError(
                    "JSON-Listen-Chunk hat unerwartete statische Felder"
                )
            collected.extend(part[list_key])
        value[list_key] = collected
    elif len(parsed_chunks) == 1:
        value = parsed_chunks[0]
    else:
        raise RuntimeError(
            "JSON-Ausgabe konnte nicht strukturerhaltend zusammengesetzt werden"
        )

    output = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    json.loads(output)
    return output


def batch_checkpoint_plan_id(
    text,
    instruction,
    detected_type,
    chunk_tokens,
    analysis,
):
    metadata = json.dumps(
        {
            "instruction": str(instruction or ""),
            "detected_type": str(detected_type or ""),
            "chunk_tokens": int(chunk_tokens),
            "chunk_strategy": analysis.get("chunk_strategy"),
            "json_list_key": analysis.get("json_list_key"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256()
    digest.update(metadata.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(text or "").encode("utf-8"))
    return digest.hexdigest()


def is_metal_oom_error(message):
    value = str(message or "").lower()

    markers = (
        "metal::malloc",
        "maximum allowed buffer size",
        "out of memory",
        "memory allocation",
    )

    return any(
        marker in value
        for marker in markers
    )
