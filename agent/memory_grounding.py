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


def person_claim_supported(subject, value, evidence):
    """Require a person and their claimed attribute in one attributed clause.

    A model may quote an entire paragraph mentioning A and C, assigning C's
    activity to A while satisfying global name/value substring checks.
    Ambiguous/pronoun-only claims remain in the original source instead.
    """
    if not str(subject).startswith('personen.'):
        return True
    name = str(subject).split('.', 1)[1]
    value = str(value).strip()
    if not name or not value:
        return False
    # Sentence boundaries and a new explicit person/action subject start a
    # new attribution scope. Avoid transferring actions to another person.
    scopes = re.split(
        r'(?<=[.!?;])\s+|\n+|'
        r'\s+\b(?:und|aber)\s+(?=(?:mit|bei|von|für|mein\w*)\b)|'
        r'\s+\b(?:und|aber)\s+(?=[A-ZÄÖÜ][\wÄÖÜäöüß-]+\s+'
        r'(?:war|ist|hat|ging|fuhr|arbeitete|wohnt)\b)',
        str(evidence),
    )
    return any(
        mentions_person(scope, name) and value.casefold() in scope.casefold()
        for scope in scopes
    )
