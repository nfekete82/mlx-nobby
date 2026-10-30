"""Truthful, bounded LTX 0.18 CLI progress parsing shared by video workloads."""
import re
import time

class ProgressTail:
    """Bounded regular-file reads; never wait for stdout or a newline."""
    def __init__(self, path):
        self.path = path
        self.reset()

    def reset(self):
        self.offset = 0
        self.pending = ""

    def read(self):
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            chunk = stream.read(65536)
            self.offset = stream.tell()
        if not chunk:
            return {}
        text = self.pending + chunk.decode("utf-8", errors="replace")
        records = re.split(r"[\r\n]", text)
        self.pending = records.pop()[-8192:]
        fields = {"last_activity_at": time.time()}
        for record in records:
            fields.update(parse_progress(record))
        fields.update(parse_progress(self.pending))
        return fields


def parse_progress(record):
    """LTX 0.18 samplers.py tqdm descriptions; fractions are phase-local."""
    record = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", record)
    match = re.search(r"(Denoising[^:]*):.*?\|\s*(\d+)\s*/\s*(\d+)", record)
    if match:
        current, total = int(match[2]), int(match[3])
        if total > 0 and 0 <= current <= total:
            return {"phase": "generating", "current_step": current, "total_steps": total,
                    "phase_progress": current / total, "progress": None,
                    "progress_scope": "phase", "progress_message": match[1]}
    # These messages come from the installed pipeline's verbose logger.
    lower = record.lower().strip().lstrip("[")
    # LTX's VAE decode log has no percentage. Clear the previous denoising
    # counter instead of leaving a misleading 67% / 88% on screen.
    if lower.startswith(("vae-decode", "vae decode", "vae_decode", "decoding")):
        return {"phase": "decoding", "progress_message": "LTX dekodiert Videoframes",
                "phase_progress": None, "progress": None,
                "current_step": None, "total_steps": None}
    for prefix, phase, message in (
        ("decoding", "decoding", "Video wird dekodiert"),
        ("loading", "loading", "LTX lädt Modelle"),
        ("encoding prompt", "encoding_prompt", "LTX kodiert den Prompt"),
        ("encoding", "encoding", "LTX kodiert Eingaben"),
        ("stage 1", "stage_1", "LTX Generierung · Stage 1"),
        ("stage 2", "stage_2", "LTX Verfeinerung · Stage 2"),
        ("saving", "saving", "Video wird gespeichert"),
    ):
        if lower.startswith(prefix):
            return {"phase": phase, "progress_message": message, "phase_progress": None,
                    "progress": None, "current_step": None, "total_steps": None}
    return {}
