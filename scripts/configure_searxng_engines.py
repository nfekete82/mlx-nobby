"""Safely add reversible SearXNG engine overrides to an existing local config.

No Docker operations, network requests, YAML rewriting or secret printing.
Use on a host-mounted settings.yml with use_default_settings: true and no
top-level engines section. Existing custom engines require manual review.

Usage:
    python scripts/configure_searxng_engines.py
    python scripts/configure_searxng_engines.py --apply
"""
import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import tempfile


ENGINE_OVERRIDES = (
    ("brave", True),
    ("duckduckgo", True),
    ("google cse", True),
    ("startpage", True),
    ("bing", False),
    ("qwant", True),
    ("yahoo", True),
    ("google", False),
    ("bpb", False),
)
# Legacy generated configuration; only this exact block can be migrated.
LEGACY_OVERRIDES = (
    ("brave", True), ("duckduckgo", True), ("google cse", True),
    ("startpage", True), ("bing", False), ("qwant", False),
    ("yahoo", False),
)
GENERATED_MARKER = "# Local overrides: disable blocked web engines; test alternatives."
DEFAULT_PATH = Path("~/searxng/config/settings.yml").expanduser()


def proposed_settings(text):
    """Append overrides without disturbing any existing keys or secrets."""
    if not re.search(r"(?m)^use_default_settings:\s*true\s*(?:#.*)?$", text):
        raise ValueError("Expected top-level use_default_settings: true; manual review required")
    if re.search(r"(?m)^engines\s*:", text):
        raise ValueError("Top-level engines overrides already present; manual review required")
    lines = ["", "# Local overrides: disable blocked web engines; test alternatives.",
             "engines:"]
    for engine, disabled in ENGINE_OVERRIDES:
        lines.extend((f"  - name: {engine}",
                      f"    disabled: {'true' if disabled else 'false'}"))
    return text.rstrip("\n") + "\n" + "\n".join(lines) + "\n"


def reconciled_settings(text):
    """Reconcile only a previous generated engine block; preserve custom YAML."""
    if not re.search(r"(?m)^engines\s*:", text):
        return proposed_settings(text)

    def generated_section(entries):
        return GENERATED_MARKER + "\nengines:\n" + "".join(
            f"  - name: {name}\n    disabled: {str(disabled).lower()}\n"
            for name, disabled in entries
        )

    old = generated_section(LEGACY_OVERRIDES)
    current = generated_section(ENGINE_OVERRIDES)
    if text.endswith(current) and text.count(current) == 1:
        return text
    if text.count(old) != 1 or not text.endswith(old):
        raise ValueError("Custom engines section detected; manual review required")
    return text[:-len(old)] + current


def configure(path, *, apply=False, reconcile=False):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("Settings must be an existing regular, non-symlink file")
    original = path.read_text(encoding="utf-8")
    modified = reconciled_settings(original) if reconcile else proposed_settings(original)
    if not apply:
        return {"applied": False, "path": str(path), "backup": None}
    # Back up the entire existing config, including secrets, locally with
    # preserved file permissions; never print its contents.
    backup = path.with_name(path.name + ".backup-" +
                            datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    shutil.copy2(path, backup)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                         dir=path.parent, prefix=".searxng-settings-",
                                         delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(modified)
        shutil.copymode(path, tmp_path)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return {"applied": True, "path": str(path), "backup": str(backup)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--apply", action="store_true",
                        help="Back up and write the config; otherwise just validate")
    parser.add_argument("--reconcile", action="store_true",
                        help="Upgrade only the exact previously generated engine overrides")
    args = parser.parse_args(argv)
    try:
        outcome = configure(args.path, apply=args.apply, reconcile=args.reconcile)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"Not modified: {exc}\n")
    if not outcome["applied"]:
        print("Dry run OK. No changes. Use --apply after reviewing the plan.")
    else:
        print("Settings updated. Private backup:", outcome["backup"])
        print("Restart only the existing SearXNG container: docker restart searxng")
    print("Disabled: brave, duckduckgo, google cse, startpage, qwant, yahoo")
    print("Enabled for testing: bing, google, bpb")


if __name__ == "__main__":
    main()
