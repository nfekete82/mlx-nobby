"""Conservative consistency check for enumerated item counts.

Only changes a matching introductory count if a consecutive top-level
numbered list immediately follows. This is text consistency, not fact checking.
"""
import re

_WORDS = {"ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4,
          "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10}
_NAMES = {value: key for key, value in _WORDS.items() if key != "eine"}
_COUNT = re.compile(r"\b(?P<count>\d{1,2}|ein|eine|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)\s+(?P<noun>iPhone-Modelle|Modelle|Geräte)\b", re.I)
_ITEM = re.compile(r"^\s*(\d{1,2})[.)]\s+\S")


def align_enumerated_count(answer):
    if not isinstance(answer, str):
        return answer
    lines = answer.splitlines(keepends=True)
    first = next((i for i, line in enumerate(lines) if _ITEM.match(line)), None)
    if first is None:
        return answer
    numbers = []
    for line in lines[first:]:
        match = _ITEM.match(line)
        if match:
            numbers.append(int(match.group(1)))
        elif numbers and line.strip() == "":
            continue
        elif numbers and not line.startswith((" ", "\t")):
            break
    if len(numbers) < 2 or numbers != list(range(1, len(numbers) + 1)):
        return answer
    count = len(numbers)
    for i in range(first):
        match = _COUNT.search(lines[i])
        if not match:
            continue
        old = match.group("count")
        stated = int(old) if old.isdigit() else _WORDS.get(old.lower())
        if stated is None or stated == count:
            return answer
        replacement = str(count) if old.isdigit() else _NAMES.get(count)
        if replacement is None:
            return answer
        if old[0].isupper():
            replacement = replacement.capitalize()
        start, end = match.span("count")
        lines[i] = lines[i][:start] + replacement + lines[i][end:]
        return "".join(lines)
    return answer
