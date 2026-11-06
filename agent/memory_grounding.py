"""Conservative source checks shared by deterministic and model extraction."""
import re


def asserted_text(text):
    """Remove attributed/quoted/example material while retaining other sentences."""
    text = re.sub(r'```[\s\S]*?(?:```|$)', ' ', str(text))
    text = re.sub(r'"[^"\n]*"|„[^“\n]*“|“[^”\n]*”|«[^»\n]*»', '. ', text)
    # Markdown quotations and single-quoted full assertions are source data.
    text = re.sub(r'(?m)^\s*>[^\n]*', ' ', text)
    text = re.sub(r"(?<!\w)'[^'\n]{4,}'(?!\w)", ' ', text)
    sentences = re.split(r'(?<=[.!?])\s+|\n+', text)
    return ' '.join(s for s in sentences if not (
        s.rstrip().endswith('?') or re.search(
            r'\b(?:wenn|falls|angenommen|hypothetisch|vielleicht|vermutlich|'
            r'if|suppose|hypothetical|maybe|perhaps|zum beispiel|for example|'
            r'zitat|quotation|beispielsatz|example sentence|sagte|schrieb|says|wrote)\b', s, re.I)))


def supported(evidence, original):
    clean = lambda value: re.sub(r'\s+', ' ', str(value)).strip().casefold()
    return bool(clean(evidence)) and clean(evidence) in clean(asserted_text(original))


def project_statements(text):
    """Only explicit named first-person project reports, preserving literal text.

    No completion, technology, relationship or person attributes are inferred.
    The semantic worker can later split a report into independently grounded
    attributes in the same subject namespace.
    """
    result = []
    for sentence in re.split(r'(?<=[.!?])\s+|\n+', asserted_text(text)):
        match = re.search(
            r'\b(?i:mein projekt\s+|ich entwickle (?:ein|eine) [^.!?]{2,65}? namens\s+)'
            r'(?P<name>[A-ZÄÖÜ][\wÄÖÜäöüß-]*(?: [A-ZÄÖÜ][\wÄÖÜäöüß-]*){0,3})'
            r'(?=\s+(?:verwendet|nutzt|ist|hat|wird)|[.!?]|$)', sentence)
        if not match: continue
        name = match['name'].casefold().replace(' ', '_')
        if 12 <= len(sentence) <= 500:
            result.append(('projekte.'+name, sentence.strip()))
    return result


def mentions_person(text, person_slug):
    """Match an explicit name as a complete sequence, never as a substring.

    The source must visibly name the person. A name in a previous chat is not
    evidence that a new pronoun/action belongs to that person.
    """
    name = re.sub(r'[_\s-]+', ' ', str(person_slug).casefold()).strip()
    source = re.sub(r'[_\s-]+', ' ', str(text).casefold()).strip()
    return bool(name and re.search(
        r'(?<!\w)' + re.escape(name) + r'(?!\w)', source
    ))


# Conservative split of independently attributed experiences. The main
# purpose is to prevent a model from borrowing a verb/action from the next
# named person's clause or from a pronoun-only continuation.
_ATTRIBUTION_BOUNDARIES = re.compile(
    r'(?<=[.!?;])\s+|\n+'
    r'|(?:\s+\b(?i:und|aber|während)\s+|,\s*)(?=(?i:mit|bei|von|für)\s+\w+)'
    r'|,\s*(?=[A-ZÄÖÜ][\wÄÖÜäöüß-]+\s+\w+)'
    r'|,\s*(?=(?i:danach|später|anschließend|dann)\b)'
    r'|\s+\b(?i:und|aber)\s+(?=(?i:sie|er|wir)\s+(?i:war|ist|hat|ging|fuhr|schwamm|machte)\b)'
    r'|\s+\b(?i:und|aber)\s+(?=[A-ZÄÖÜ][\wÄÖÜäöüß-]+\s+(?i:war|ist|hat|ging|fuhr|schwamm|machte|arbeitete|wohnt)\b)'
)


def attributed_clauses(evidence):
    """Literal local spans. Do not assign pronouns to earlier named people.

    This is intentionally not an NLP coreference engine. If an action only
    occurs in a different span, the named person's evidence is insufficient.
    """
    return [part.strip() for part in _ATTRIBUTION_BOUNDARIES.split(
        str(evidence or '')
    ) if part.strip()]


def person_scoped_excerpt(evidence, person_slug, *, limit=1000):
    """Read-only verbatim evidence spans visibly naming the requested person."""
    spans = [
        part for part in attributed_clauses(evidence)
        if mentions_person(part, person_slug)
    ]
    return ' … '.join(spans)[:limit]


def person_claim_supported(subject, value, evidence):
    """Require named actor and claimed attribute in the same evidence span.

    Both names and the activity existing somewhere in the same paragraph is
    insufficient. A pronoun-only continuation cannot silently become a new
    fact about the previously named person.
    """
    if not str(subject).startswith('personen.'):
        return True
    name = str(subject).split('.', 1)[1]
    value = str(value).strip()
    if not name or not value:
        return False
    return any(
        mentions_person(scope, name) and value.casefold() in scope.casefold()
        for scope in attributed_clauses(evidence)
    )
