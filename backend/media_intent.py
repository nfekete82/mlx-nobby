"""Shared, side-effect-free authorization for natural-language media routing.

Commands bind to their first output object. Text objects and questions are
handled before media; attachment/model/adult vocabulary is context only.
Semantic classifiers may refine non-media routes, never authorize media jobs.
"""
from dataclasses import asdict, dataclass
import re
from pathlib import Path

MEDIA_ACTIONS = frozenset({
    "image_generate", "image_edit", "image_upscale", "video_generate",
    "video_animate", "shorts_generate",
})
TARGETS = {
    "image_generate": "image", "image_edit": "image_edit",
    "image_upscale": "image", "video_generate": "video",
    "video_animate": "video", "shorts_generate": "shorts_generate",
}
CREATE = set(
    "erstelle erstell erstellen generiere generier generieren erzeuge erzeugen zeichne zeichnen male malen "
    "mach mache machen render rendere rendern produziere produzieren create generate draw paint "
    "make render produce build turn convert "
    .split()
)
EDIT = set(
    "bearbeite bearbeiten ändere ändern aendere aendern verändere verändern veraendere veraendern färbe färben "
    "faerbe faerben entferne entfernen lösche löschen loesche loeschen ersetze ersetzen füge fuege "
    "retuschiere korrigiere verbessere verbessern change edit modify recolor remove replace add retouch "
    "blur "
    .split()
)
ANIMATE = set(
    "animiere animieren animate "
    .split()
)
START = set(
    "starte start launch "
    .split()
)
TEXT_OBJECTS = set(
    "prompt prompts bildprompt imageprompt videoprompt skript script skripte screenplay formulierung beschreibung description "
    "empfehlung recommendation erklärung explanation anleitung instructions "
    .split()
)
QUESTIONS = set(
    "was wie welche welcher welches welchen wer wo wann warum ist sind "
    "hat haben what how which who where when why is are does "
    "has have "
    .split()
)
DISCUSS = set(
    "beschreibe beschreiben erkläre erklären erklaere erklaeren empfehle analysiere bewerte vergleiche describe explain "
    "recommend analyze analyse review evaluate compare tell "
    .split()
)
OBJECTS = {
    **dict.fromkeys("bild bilder foto photo image picture illustration grafik graphic porträt portrait headshot".split(), "image_generate"),
    **dict.fromkeys("video clip animation film movie".split(), "video_generate"),
    **dict.fromkeys("short shorts tiktok reel reels kurzvideo kurzvideos".split(), "shorts_generate"),
}
MODIFIERS = set(
    "rot blau grün gruen gelb schwarz weiß weiss blond heller dunkler dunkel "
    "hell warm wärmer waermer kälter kaelter jünger juenger älter aelter unscharf scharf weg "
    "hintergrund farbe farben gesicht haare bart kleidung stil realistischer ganzkörper ganzkoerper größer "
    "groesser kleiner red blue green yellow black white blonde lighter darker dark "
    "bright younger older blurry blurred sharp background color colour face hair beard "
    "clothing style warmer cooler realistic full body zoom longer shorter näher naeher "
    "länger laenger kürzer kuerzer schärfer schaerfer "
    .split()
)
NEGATIONS = set(
    "nicht kein keine keinen keines niemals not never don't dont "
    .split()
)


# Negation can qualify a requested appearance rather than cancel the command.
# Keep image referents out of this vocabulary: "not the background" withholds
# an operation, while "background not so bright" specifies its desired result.
EDIT_PROPERTIES = MODIFIERS - set(
    "hintergrund farbe farben gesicht haare bart kleidung stil ganzkörper ganzkoerper "
    "background color colour face hair beard clothing style full body zoom".split()
)
DEGREE_WORDS = {"so", "zu", "too", "as", "very", "ganz", "sehr", "viel", "much"}
CONTENT_CONSTRAINTS = {
    "logo", "logos", "marke", "marken", "brand", "brands", "branding",
    "wasserzeichen", "watermark", "watermarks", "text", "voiceover",
}
CONTENT_QUALIFIERS = {"generierter", "generierte", "generierten", "generiertes", "generated"}


def _negates_execution(words, command):
    """Bind negation to the command or to the following appearance property."""
    for index, word in enumerate(words):
        if word not in NEGATIONS:
            continue
        following = index + 1
        while following < len(words) and words[following] in CONTENT_QUALIFIERS:
            following += 1
        if following < len(words) and words[following] in CONTENT_CONSTRAINTS:
            # "Kein Text im Bild" restricts content, not media execution. In a
            # command clause, require an already bound media output so that
            # "Erstelle keinen Text ..." still withholds the requested output.
            if command is None or any(word in OBJECTS for word in words[command + 1:index]):
                continue
        if command is not None and index > command and word in {"nicht", "not"}:
            following = index + 1
            while following < len(words) and words[following] in DEGREE_WORDS:
                following += 1
            if following < len(words) and words[following] in EDIT_PROPERTIES:
                continue
        # Negation before the verb, a negative output determiner (kein Bild),
        # or a command without a negated property cancels execution.
        return True
    return False


def has_image_context(context=None, active_artifact_id=None):
    """Interpret attachment metadata only; never inspect image bodies."""
    if active_artifact_id:
        return True
    if not isinstance(context, dict):
        return False
    if str(context.get("kind", "")).lower() == "image":
        return True
    mime = str(context.get("mime_type") or context.get("mime") or context.get("type") or "").lower()
    if mime.startswith("image/"):
        return True
    name = context.get("stored_path") or context.get("path") or context.get("name") or context.get("filename") or ""
    return Path(str(name)).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".heic", ".heif", ".avif"}


@dataclass(frozen=True)
class RoutingDecision:
    intent: str
    target: str
    execution_requested: bool
    media_context: str | None
    confidence: float
    reason: str
    guard: str | None = None
    fallback: str | None = None

    @property
    def handles_turn(self):
        return self.execution_requested or self.intent in {"prompt_writing", "discussion", "vision_chat"}

    def payload(self):
        return asdict(self)

    def chat_routing(self):
        return self.payload() | {
            "intent": self.intent if self.execution_requested else "normal_chat",
            "detected_intent": self.intent,
            "requires_tools": self.execution_requested,
            "method": "central_media_intent",
        }


def decide_media_intent(prompt, *, has_image=False, action=None):
    """Decide from the current instruction, never from conversation history.

    Explicit UI actions authorize bare media descriptions. They cannot override
    a text request or negation. Quoted examples are not execution instructions.
    Independent clauses allow 'improve the prompt and generate the image'.
    """
    text = str(prompt or "").casefold().strip()
    # Drop quoted payloads; preserve the surrounding user's instruction.
    text = re.sub(r'```[\s\S]*?```|"[^"\n]*"|„[^“]*“|“[^”]*”', ' ', text)
    # Treat medium adjectives in text-output nouns as a single text object.
    text = re.sub(r"\b(?:image|video|short|bild|ltx)[ -]+(prompt|script|skript)\b", r"\1", text)
    clauses = re.split(r'[;.!?\n]+|\b(?:und|and)\b', text)
    media_context = "image" if has_image else None
    text_intent = None
    topics = set(OBJECTS) | TEXT_OBJECTS | {"ltx", "porträtfotografie", "portraitfotografie", "photography"}
    execution = None
    negated = False
    for clause in clauses:
        words = re.findall(r"[^\W_]+(?:'t)?", clause, re.UNICODE)
        if not words:
            continue
        command = next((i for i, word in enumerate(words)
                        if word in CREATE | EDIT | ANIMATE | START), None)
        if _negates_execution(words, command) and (has_image or set(words) & topics):
            negated = True
            continue
        if (words[0] in QUESTIONS or set(words[:6]) & DISCUSS) and (has_image or set(words) & topics):
            text_intent = "prompt_writing" if set(words) & TEXT_OBJECTS else "discussion"
            continue
        # Bind to the command's output, rather than a preceding context noun.
        objects = [(i, word) for i, word in enumerate(words)
                   if word in TEXT_OBJECTS or word in OBJECTS]
        outputs = [(i, word) for i, word in objects if command is None or i > command]
        first_object = outputs[0][1] if outputs else (objects[0][1] if objects else None)
        if first_object in TEXT_OBJECTS:
            text_intent = "prompt_writing"
            continue
        if command is None:
            leading = next((word for word in words if word not in {"bitte", "please", "jetzt", "nun", "noch", "now", "then", "mehr", "etwas", "ein", "bisschen", "more", "a", "bit"}), "")
            if has_image and leading in MODIFIERS | {"weiter"}:
                execution = "image_edit"
            continue
        # Subordinate intent belongs to the description, not to a new command.
        if set(words[:command]) & {"damit", "wenn", "if", "so", "dass", "that"}:
            continue
        verb = words[command]
        if verb in ANIMATE:
            execution = "video_animate"
        elif verb in START and "ltx" in words[command + 1:]:
            execution = "video_animate" if has_image else "video_generate"
        elif verb in EDIT and has_image:
            execution = "image_edit"
        elif verb in CREATE:
            if first_object in OBJECTS:
                execution = OBJECTS[first_object]
                if (execution == "image_generate" and has_image and verb in {"mach", "mache", "make"}
                        and set(words) & MODIFIERS and not set(words) & {"ein", "eine", "einen", "a", "an", "new", "neues"}):
                    execution = "image_edit"
                if execution == "video_generate" and (
                    has_image or set(words) & {"daraus", "hieraus", "this", "that"}
                ):
                    execution = "video_animate"
            elif has_image and set(words[command + 1:]) & MODIFIERS:
                execution = "image_edit"
    if execution and not negated:
        return RoutingDecision(execution, TARGETS[execution], True, media_context,
                               1.0, "Explicit command bound to media output")
    if text_intent or negated:
        intent = text_intent or "discussion"
        return RoutingDecision(intent, "chat", False, media_context, 1.0,
                               "User requests text or withholds media execution",
                               "text_request_priority", "chat")
    if action in MEDIA_ACTIONS:
        return RoutingDecision(action, TARGETS[action], True, media_context, 1.0,
                               "Explicit media UI action")
    return RoutingDecision("vision_chat" if has_image else "normal_chat", "chat",
                           False, media_context, 1.0,
                           "Image is context only" if has_image else "No explicit media execution",
                           "execution_required", "chat")
