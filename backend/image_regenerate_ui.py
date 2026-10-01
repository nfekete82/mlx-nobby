"""Remove the redundant fixed-count regenerate button from image cards."""

from __future__ import annotations


IMAGE_SETTINGS_JS_PATH = "/assets/chat/image-settings.js"

_VARIANT_DECLARATION = "        const variants = document.createElement('button');\n"
_VARIANT_SETUP = """        variants.type = 'button';
        variants.className = 'message-action-btn';
        variants.textContent = '3× ' + imageT(
            'ui.regenerate',
            'Regenerate'
        );
        variants.title = variants.textContent;

"""
_VARIANT_HANDLER = """        variants.addEventListener('click', async () => {
            regenerate.disabled = true;
            variants.disabled = true;
            const originalLabel = variants.textContent;
            variants.textContent = imageT(
                'common.loading',
                'Loading…'
            );

            const started = await generateImageVariants(source, 3);

            if (!started && variants.isConnected) {
                regenerate.disabled = false;
                variants.disabled = false;
                variants.textContent = originalLabel;
            }
        });

"""


def patch_image_settings_source(body: bytes) -> bytes:
    """Keep single regeneration while removing the hard-coded 3× card action.

    Multi-image generation remains available through the normal image-count
    picker and the variant-gallery runtime; only the redundant card shortcut is
    removed.
    """
    patched = body

    replacements = (
        (_VARIANT_DECLARATION, ""),
        (_VARIANT_SETUP, ""),
        ("            variants.disabled = true;\n", ""),
        ("                variants.disabled = false;\n", ""),
        (_VARIANT_HANDLER, ""),
        (
            "        fragment.append(regenerate, variants, enhanceMenu);",
            "        fragment.append(regenerate, enhanceMenu);",
        ),
    )

    for old, new in replacements:
        old_bytes = old.encode("utf-8")
        if old_bytes in patched:
            patched = patched.replace(old_bytes, new.encode("utf-8"), 1)

    return patched


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
