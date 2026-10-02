"""Small deterministic person-reference vocabulary shared by media routing."""
import re

REFERENCE_VERBS = frozenset('zeige zeigen show keep preserve behalte behalten beibehalten'.split())
PERSON_REFERENCE = re.compile(
    r'\b(?:(?:dies(?:e|er|elbe|elben)|derselben|demselben|denselben|gleiche[nmrs]?|gleichen|dieses|gleiches|dasselbe|demselben)\s+(?:person|gesicht|frau|mann)|'
    r'(?:person|frau|mann|sie|ihn)\s+(?:aus|auf)\s+(?:dem|diesem)\s+(?:bild|foto)|'
    r'(?:same|this)\s+(?:person|face|woman|man)|person\s+(?:in|from)\s+(?:this|the)\s+(?:image|photo)|'
    r'(?:behalte|beibehalten|keep|preserve)\s+(?:(?:das|die|the)\s+)?(?:gesicht|person|aussehen|face|identity)|'
    r'(?:gesicht|person|aussehen)\s+beibehalten)\b', re.I)
RESEMBLANCE = re.compile(r'\b(?:ähnelt|aehnelt|ähnlich|aehnlich|resembling|resembles|resemble|similar\s+to|looks\s+like|sieht\s+aus\s+wie)\b', re.I)
REFERENCE_FOLLOWUP = re.compile(r'^\s*(?:und\s+)?(?:jetzt|nun|now|this time)\s+(?:draußen|draussen|drinnen|im|in|mit|ohne|outside|indoors|outdoors|in|with|without)\b', re.I)


def reference_mode(prompt):
    if not PERSON_REFERENCE.search(str(prompt or '')):
        return None
    return 'resemblance' if RESEMBLANCE.search(str(prompt)) else 'same_identity'


def reference_instruction(mode, prompt):
    if mode == 'same_identity':
        instruction = "Use the source photo as a visual reference. Preserve the person's recognizable facial identity and characteristic features as far as possible."
    else:
        instruction = 'Use the person in the source photo as a visual reference for recognizable resemblance; exact identity is not required.'
    return instruction + ' Follow the requested scene and clothing; do not copy the original setting unless requested. User instruction: ' + prompt
