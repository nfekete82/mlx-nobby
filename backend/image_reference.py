"""Small deterministic person-reference vocabulary shared by media routing."""
import re

REFERENCE_VERBS = frozenset('zeige zeigen show keep preserve behalte behalten beibehalten'.split())
PERSON_REFERENCE = re.compile(
    r'\b(?:(?:dies(?:e|er|elbe|elben)|derselben|demselben|denselben|gleiche[nmrs]?|gleichen|dieses|gleiches|dasselbe|demselben)\s+(?:person|gesicht|frau|mann)|'
    r'(?:person|frau|mann|sie|ihn)\s+(?:aus|auf)\s+(?:dem|diesem)\s+(?:bild|foto)|'
    r'(?:exact(?:ly)?\s+)?(?:same|this)\s+(?:(?:adult|young|older|middle-aged|elderly)\s+){0,2}(?:person|face|woman|man)|person\s+(?:in|from)\s+(?:this|the)\s+(?:image|photo)|'
    r'(?:behalte|beibehalten|keep|preserve)\s+(?:(?:das|die|the)\s+)?(?:gesicht|person|aussehen|face|identity)|'
    r'(?:gesicht|person|aussehen)\s+beibehalten)\b', re.I)
RESEMBLANCE = re.compile(r'\b(?:ähnelt|aehnelt|ähnlich|aehnlich|resembling|resembles|resemble|similar\s+to|looks\s+like|sieht\s+aus\s+wie)\b', re.I)
# Strong identity requests outrank soft qualifiers such as "möglichst ähnlich".
# "Ein Bild, das dieser Person ähnelt" still means resemblance, not identity.
EXACT_IDENTITY = re.compile(
    r'\b(?:dieselbe[nr]?|derselben|demselben|denselben|gleiche[nmrs]?|gleichen|dasselbe[nr]?|same|identical|exact\s+same)\s+'
    r'(?:(?:adult|young|older|middle-aged|elderly)\s+){0,2}(?:person|gesicht|frau|mann|face|woman|man)\b|'
    r'\b(?:behalte|beibehalten|bewahre|erhalte|keep|preserve|retain)\b.{0,80}'
    r'\b(?:person|gesicht|gesichtszüge|aussehen|identität|face|identity|appearance)\b|'
    r'\b(?:facial\s+identity|same\s+facial\s+features)\b',
    re.I,
)
POSE_CHANGE = re.compile(
    r'\b(?:neue[nr]?\s+pose|andere[nr]?\s+pose|anderen?\s+haltung|'
    r'ganzkörper(?:aufnahme|foto)?|full[ -]?body|new\s+pose|different\s+pose|'
    r'standing|sitting|walking|steht|sitz(?:t|end)|läuft|gehen|'
    r'arms?|hände?|hands?|posture|body\s+position)\b',
    re.I,
)
REFERENCE_FOLLOWUP = re.compile(r'^\s*(?:und\s+)?(?:jetzt|nun|now|this time)\s+(?:draußen|draussen|drinnen|im|in|mit|ohne|outside|indoors|outdoors|in|with|without)\b', re.I)


def reference_mode(prompt):
    if not PERSON_REFERENCE.search(str(prompt or '')):
        return None
    text = str(prompt or '')
    if EXACT_IDENTITY.search(text):
        return 'same_identity'
    return 'resemblance' if RESEMBLANCE.search(text) else 'same_identity'


def reference_instruction(mode, prompt):
    if mode == 'same_identity':
        instruction = "Use the source photo as a visual reference. Preserve the person's recognizable facial identity and characteristic features as far as possible."
    else:
        instruction = 'Use the person in the source photo as a visual reference for recognizable resemblance; exact identity is not required.'
    if mode == 'same_identity' and POSE_CHANGE.search(prompt):
        instruction += (
            " If a new body pose or full-body view is requested, create a new "
            "composition with the specified pose, arms and camera framing; "
            "do not reproduce the original selfie crop or seated posture "
            "unless requested."
        )
    return instruction + ' Follow the requested scene and clothing; do not copy the original setting unless requested. User instruction: ' + prompt
