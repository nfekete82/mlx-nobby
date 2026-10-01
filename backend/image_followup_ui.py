"""Keep the active generated image in scope for natural visual follow-ups."""

from __future__ import annotations


GENERATION_JS_PATH = "/assets/chat/generation.js"

_OLD_REFERENCE_PATTERN = (
    r"/\b(?:das|dieses|diesem|dieser|bild|foto|abbildung|es|davon|darauf)\b|"
    r"\bist\s+das\b|\bsieht\s+(?:das|es)\b/i"
)
_NEW_REFERENCE_PATTERN = (
    r"/\b(?:das|dieses|diesem|dieser|bild|foto|abbildung|aufnahme|porträt|portrait|"
    r"porträtfotografie|portraitfotografie|fotografie|photography|photograph|image|picture|"
    r"es|davon|darauf)\b|\bist\s+das\b|\bsieht\s+(?:das|es)\b/i"
)

_OLD_MESSAGE_CONTENT = "        content: messageContent,\n        display_content: effectivePrompt,"
_NEW_MESSAGE_CONTENT = """        content: (
            visionImages.length && refersToExistingImage
                ? messageContent +
                    '\\n\\nThe active generated image is attached for context. Refer to and analyze that image directly when answering this question.'
                : messageContent
        ),
        display_content: effectivePrompt,"""


def patch_generation_source(body: bytes) -> bytes:
    """Expand the existing active-image detector and make the reference explicit.

    The generation module already resolves the active artifact and attaches it to
    the vision request. This patch teaches that path natural follow-ups such as
    "Was hältst du von Porträtfotografie?" and adds a model-only context hint
    after an image was actually attached. The visible user text stays unchanged.
    """
    patched = body

    old_reference = _OLD_REFERENCE_PATTERN.encode("utf-8")
    new_reference = _NEW_REFERENCE_PATTERN.encode("utf-8")
    if new_reference not in patched and old_reference in patched:
        patched = patched.replace(old_reference, new_reference, 1)

    old_content = _OLD_MESSAGE_CONTENT.encode("utf-8")
    new_content = _NEW_MESSAGE_CONTENT.encode("utf-8")
    if new_content not in patched and old_content in patched:
        patched = patched.replace(old_content, new_content, 1)

    return patched


class ImageFollowupUiMiddleware:
    """Patch the served chat generation module without forking the large JS file."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")
        if method != "GET" or path != GENERATION_JS_PATH:
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
                await send({"type": "http.response.body", "body": part, "more_body": True})
            body_parts.clear()
            await send(message)

        await self.app(child_scope, receive, capture)

        if passthrough or start_message is None:
            return

        body = b"".join(body_parts)
        if int(start_message.get("status") or 200) == 200:
            patched = patch_generation_source(body)
            if patched != body:
                body = patched
                headers = [
                    (key, value)
                    for key, value in list(start_message.get("headers") or [])
                    if key.lower() not in {b"content-length", b"etag"}
                ]
                headers.append((b"content-length", str(len(body)).encode("ascii")))
                start_message["headers"] = headers

        await send(start_message)
        await send({"type": "http.response.body", "body": body, "more_body": False})
