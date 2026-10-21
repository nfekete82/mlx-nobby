"""Preserve the original mlx_vlm.server.cli arguments but wrap its ASGI app."""
import importlib
import os
import sys

import uvicorn


def main():
    # Only allow explicit opt-in. Normal production startup is unchanged.
    if os.environ.get('MLX_LIFECYCLE_ENABLE') != '1':
        raise SystemExit('Lifecycle launcher requires MLX_LIFECYCLE_ENABLE=1')
    original = uvicorn.run
    uvicorn_main = importlib.import_module('uvicorn.main')
    previous = uvicorn_main.run

    def intercept(application, *args, **kwargs):
        # MLX-VLM CLI versions sometimes use a string, others an app object.
        if application in ('mlx_vlm.server:app', 'mlx_vlm.server.app:app'):
            pass
        else:
            from mlx_vlm.server.app import app as upstream
            if application is not upstream:
                raise RuntimeError('Unrecognized MLX-VLM ASGI target; refusing startup')
        return original('model_lifecycle_asgi:app', *args, **kwargs)

    uvicorn.run = intercept
    uvicorn_main.run = intercept
    try:
        # Original invocation is: python -m mlx_vlm server --host ...
        # server.cli.main expects the options but not the 'server' verb.
        if len(sys.argv) > 1 and sys.argv[1] == 'server':
            sys.argv.pop(1)
        from mlx_vlm.server.cli import main as server_main
        server_main()
    finally:
        uvicorn.run = original
        uvicorn_main.run = previous


if __name__ == '__main__':
    main()
