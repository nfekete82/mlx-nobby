"""Build the text chat router inputs without duplicating the current turn.

The agent's conservative zero-inference fast path is only valid when the
conversation history is genuinely empty. Including the current user prompt in
its own `conversation_context` made that fast path unreachable from web chat.
"""


def route_inputs(messages):
    """Return (latest text user prompt, preceding text-only conversation).

    The prompt is passed separately to /api/chat/route. Prior turns are
    bounded exactly like the existing web bridge (eight turns, 2000 chars each).
    Only the latest matching user turn is excluded; equal text in an earlier
    user turn is genuine history and must remain.
    """
    if not isinstance(messages, (list, tuple)):
        return "", []

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue

        history = []
        for entry in messages[max(0, index - 8):index]:
            if not isinstance(entry, dict):
                continue
            role = str(entry.get("role") or "").strip().lower()
            prior_content = entry.get("content")
            if role in {"user", "assistant"} and isinstance(prior_content, str) and prior_content.strip():
                history.append({
                    "role": role,
                    "content": prior_content[:2000],
                })
        return content.strip(), history

    return "", []
