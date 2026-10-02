"""Remove the redundant fixed-count regenerate button from image cards."""

from __future__ import annotations


IMAGE_SETTINGS_JS_PATH = "/assets/chat/image-settings.js"


def patch_image_settings_source(body: bytes) -> bytes:
    """Remove the fixed-count shortcut atomically from the served card actions.

    Match block boundaries rather than the availability-dependent contents.
    If the module shape changes, serve it intact instead of leaving references
    to a deleted button declaration.
    """
    wrapper = b"    generation.createImageUpscaleMenu = source => {"
    declaration = b"        const variants = document.createElement('button');\n"
    setup = b"        variants.type = 'button';"
    regenerate = b"        regenerate.addEventListener('click', async () => {"
    handler = b"        variants.addEventListener('click', async () => {"
    append = b"        fragment.append(regenerate, variants, enhanceMenu);"
    markers = (wrapper, declaration, setup, regenerate, handler, append)
    if any(body.count(marker) != 1 for marker in markers):
        return body
    positions = [body.index(marker) for marker in markers]
    if positions != sorted(positions):
        return body
    prefix = body[:positions[0]]
    suffix = body[positions[-1] + len(append):]
    card = body[positions[0]:positions[-1]]
    card = card[:card.index(handler)]
    card = card[:card.index(setup)] + card[card.index(regenerate):]
    card = card.replace(declaration, b"")
    # Only the single-regeneration handler remains in this scoped block.
    card = b"".join(line for line in card.splitlines(keepends=True)
                    if b"variants.disabled =" not in line)
    if b"variants" in card:
        return body
    return prefix + card + b"        fragment.append(regenerate, enhanceMenu);" + suffix


class ImageRegenerateUiMiddleware:
    """Patch the served image-settings module without forking the large JS file."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")
        if method != "GET" or path != IMAGE_SETTINGS_JS_PATH:
            await self.app(scope, receive, send)
            return

        child_scope = dict(scope)
        extensions = dict(scope.get("extensions") or {})
        extensions.pop("http.response.pathsend", None)
        child_scope["extensions"] = extensions

        start_message = None
        body_parts = []
        passthrough = False

        async def capture(message):
            nonlocal start_message, passthrough
            message_type = message.get("type")

            if passthrough:
                await send(message)
                return
            if message_type == "http.response.start":
                start_message = dict(message)
                return
            if message_type == "http.response.body":
                body_parts.append(message.get("body", b""))
                return

            passthrough = True
            if start_message is not None:
                await send(start_message)
                start_message = None
            for part in body_parts:
                await send({
                    "type": "http.response.body",
                    "body": part,
                    "more_body": True,
                })
            body_parts.clear()
            await send(message)

        await self.app(child_scope, receive, capture)

        if passthrough or start_message is None:
            return

        body = b"".join(body_parts)
        if int(start_message.get("status") or 200) == 200:
            patched = patch_image_settings_source(body)
            if patched != body:
                body = patched
                headers = [
                    (key, value)
                    for key, value in list(start_message.get("headers") or [])
                    if key.lower() not in {b"content-length", b"etag"}
                ]
                headers.append((
                    b"content-length",
                    str(len(body)).encode("ascii"),
                ))
                start_message["headers"] = headers

        await send(start_message)
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })
