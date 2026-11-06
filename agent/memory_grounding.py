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
