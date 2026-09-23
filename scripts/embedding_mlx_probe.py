"""Health probe for the mlx-serve backed embedding adapter."""

import json
import urllib.request


URL = "http://127.0.0.1:8020/health"


def main():
    request = urllib.request.Request(
        URL,
        headers={
            "Accept":
                "application/json"
        },
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=15,
    ) as response:
        payload = json.loads(
            response
            .read()
            .decode("utf-8")
        )

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
        ),
        flush=True,
    )

    if not payload.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
