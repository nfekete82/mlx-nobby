"""Minimal, side-effect-free MLX Metal probe for the embedding LaunchAgent."""

import json
import os
import platform
import sys
from importlib.metadata import version


def main() -> None:
    result = {
        "python": sys.executable,
        "python_version": sys.version,
        "cwd": os.getcwd(),
        "user": os.environ.get("USER"),
        "home": os.environ.get("HOME"),
        "path": os.environ.get("PATH"),
        "tmpdir": os.environ.get("TMPDIR"),
        "display": os.environ.get("DISPLAY"),
        "platform": platform.platform(),
    }
    try:
        import mlx.core as mx

        result.update(
            {
                "ok": True,
                "mlx_version": version("mlx"),
                "default_device": str(mx.default_device()),
            }
        )
    except BaseException as exc:
        result.update({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
        print(json.dumps(result, ensure_ascii=False), flush=True)
        raise
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
