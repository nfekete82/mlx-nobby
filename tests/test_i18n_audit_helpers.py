"""The UI scan must distinguish translated fallback pairs from German contracts."""
import ast
from pathlib import Path
import re

from backend.video_errors import INVALID_VIDEO, MESSAGES
from backend.media_errors import INVALID_IMAGE_REQUEST


source = ast.parse((Path(__file__).resolve().parents[1] / "scripts/i18n-audit.py").read_text())
namespace = {"re": re}
for node in source.body:
    if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == "ALLOWLIST" for name in node.targets):
        namespace["ALLOWLIST"] = ast.literal_eval(node.value)
    if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == "GERMAN_PATTERN" for name in node.targets):
        exec(compile(ast.Module(body=[node], type_ignores=[]), "i18n-german-pattern", "exec"), namespace)
    if isinstance(node, ast.FunctionDef) and node.name in {"clean_value", "is_allowed", "js_line_is_translated"}:
        exec(compile(ast.Module(body=[node], type_ignores=[]), "i18n-audit-helpers", "exec"), namespace)


def test_keyed_bilingual_editor_fallback_is_translated():
    check = namespace["js_line_is_translated"]
    assert check('tr("cancel", "Bearbeitung abbrechen", "Cancel edit")')
    assert check('t("Schließen", "Close")')
    assert not check('tr("cancel", "Bearbeitung abbrechen")')
    assert not check('label.textContent = "Bearbeitung abbrechen";')
    assert check('loading: ["LTX lädt Modelle", "Loading LTX models"]')
    assert not check('labels: ["Speichern", "Löschen"]')
    assert not check('loading: ["LTX lädt Modelle"]')


def test_german_public_error_contracts_are_allowed_without_blanket_suppression():
    assert namespace["is_allowed"](INVALID_VIDEO)
    assert namespace["is_allowed"](INVALID_IMAGE_REQUEST)
    for message in MESSAGES.values():
        assert namespace["is_allowed"](message)
    assert not namespace["is_allowed"]("Nicht übersetzter neuer Fehler")
