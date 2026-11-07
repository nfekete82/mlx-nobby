"""Bounded local query normalization shared by the existing knowledge index.

Concept families bridge languages; vocabulary matching handles previously
unseen compounds. Neither operation supplies facts, entity names or answers.
"""
import re
import unicodedata


MAX_TERMS = 96
MAX_VOCABULARY = 20000
STOPWORDS = set('''what which how does did called use uses using my
    the and for with from have know remember about why that this is are was
    milyen hasznal hasznalja az egy en mi neve miert projektem projekthez
    heisst heisse welche welcher welches welchen meine meinem meinen meiner
    dafur deinen gespeicherten erinnerungen informationen nenne nur verwende
    verwendet verwenden nutzt nutzen beispiel beispiele beispielsweise example examples'''.split())

# Small, inspectable concept families, not a list of example-specific queries.
# Morphological/vocabulary matching below remains independent of these terms.
CONCEPTS = (
    ('spiel', 'spiele', 'spielen', 'game', 'games', 'gaming', 'jatek', 'jatekom'),
    ('strategie', 'strategy', 'strategic', 'strategiai', 'rts'),
    ('technologie', 'technologien', 'technology', 'technologies', 'technologia', 'technologiat', 'technik'),
    ('datenbank', 'database', 'databases', 'adatbazis', 'adatbazist'),
    ('aufgabe', 'aufgaben', 'task', 'tasks', 'tracker', 'feladatkezelo', 'feladatkezelom'),
    ('bewasserung', 'irrigation', 'ontozes', 'ontozesi'),
    ('energie', 'energy', 'energia', 'energiafigyelo'),
    ('datensicherung', 'backup', 'backups', 'biztonsagi', 'mentes', 'mentesem'),
    ('terminplanung', 'scheduling', 'schedule', 'idoponttervezo', 'idoponttervezom'),
    ('farbe', 'farben', 'color', 'colors', 'colour', 'colours', 'szin', 'szinek', 'szineket'),
    ('vorliebe', 'vorlieben', 'bevorzuge', 'prefer', 'preference', 'preferences', 'kedvelek'),
    ('bild', 'bilder', 'bildern', 'picture', 'pictures', 'image', 'images', 'kep', 'kepek', 'kepeken'),
    ('entscheidung', 'entschieden', 'gewahlt', 'choose', 'chose', 'chosen', 'decision', 'valasztottam'),
    ('projekt', 'projekte', 'project', 'projects', 'projektem'),
    ('beruf', 'beruflich', 'occupation', 'employment', 'profession', 'foglalkozas'),
    ('wohnort', 'wohne', 'residence', 'live', 'lakom'),
)


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text).casefold())
                   if not unicodedata.combining(c))


def stems(word):
    word = fold(word)
    result = {word}
    # Conservative inflections, not arbitrary prefix truncation.
    for suffix in ('ern', 'em', 'en', 'er', 'es', 'om', 'am', 'et', 'e', 's'):
        if word.endswith(suffix) and len(word)-len(suffix) >= 6:
            result.add(word[:-len(suffix)])
    return result


def expand(words):
    result = list(dict.fromkeys(fold(w) for w in words if fold(w) not in STOPWORDS))
    originals = list(result)
    for family in CONCEPTS:
        if any(w in family or any((len(term) >= 6 and term in w) or
                                 (len(term) >= 5 and w.endswith(term)) for term in family)
               for w in originals):
            result.extend(family)
    return list(dict.fromkeys(result))[:MAX_TERMS]


def vocabulary_terms(conn, words):
    """Use the actual index vocabulary, bounded independently of archive size.

    TEMP fts5vocab does not migrate/rewrite the persistent database. Unicode61
    folds accents as this module does. At most 20k indexed tokens are examined;
    embeddings remain the fallback for larger/unrelated vocabularies.
    """
    components = {term for family in CONCEPTS for term in family if len(term)>=5}
    roots = {root for w in words for root in stems(w) if len(root) >= 6 or root in components}
    if not roots:
        return words
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.memory_query_vocab USING fts5vocab(main, knowledge_fts, 'row')")
    result = list(words)
    for row in conn.execute('SELECT term FROM memory_query_vocab WHERE length(term)>=6 LIMIT ?', (MAX_VOCABULARY,)):
        token = row[0]
        folded = fold(token)
        if any(root in folded and (folded.startswith(root) or folded.endswith(root)
                                 or len(root) >= 9) for root in roots):
            result.append(token)
            if len(set(result)) >= MAX_TERMS:
                break
    return list(dict.fromkeys(result))[:MAX_TERMS]


def relevance(words, text):
    tokens = set(re.findall(r'[^\W_][\w-]{2,}', fold(text)))
    # Count matched index terms only once; translations are alternative routes,
    # not independent evidence. Longer anchors outrank generic attribute terms.
    matched = tokens & set(words)
    return sum(1 + min(len(token), 18)/18 for token in matched)


# A question about model names must not be answered by a nickname or job
# description that merely shares a project/name token. Do not use these
# patterns to claim that a particular model belongs to a particular project:
# the original stored source must still establish that relationship.
_AI_MODEL_QUESTION = re.compile(
    r"(?<!\w)(?:ki[- ]?)?(?:modell\w*|models?|llms?|"
    r"sprachmodell\w*|bildmodell\w*|videomodell\w*)\b", re.I,
)
_AI_MODEL_EVIDENCE = re.compile(
    r"(?<!\w)(?:ki[- ]?modell\w*|modell\w*|models?|llms?|"
    r"sprachmodell\w*|bildmodell\w*|videomodell\w*|"
    r"qwen[\w.-]*|llama[\w.-]*|gpt[\w.-]*|"
    r"claude[\w.-]*|gemini[\w.-]*|deepseek[\w.-]*|"
    r"mistral[\w.-]*|gemma[\w.-]*|phi-?[\w.-]*\d|"
    r"flux[\w.-]*|sdxl[\w.-]*|juggernaut[\w.-]*|"
    r"ltx[\w.-]*|minimax[\w.-]*|stable diffusion|"
    r"embedding[- ]?modell\w*)\b", re.I,
)


def asks_about_ai_models(query):
    return bool(_AI_MODEL_QUESTION.search(str(query)))


def has_ai_model_evidence(text):
    return bool(_AI_MODEL_EVIDENCE.search(str(text)))
