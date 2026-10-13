"""Deterministic opt-in role routing; no inference, downloads or configuration writes."""
import re


def select_chat_role(messages, roles, available_roles, *, enabled=False):
    # A persisted manual chat selection always wins over automatic routing.
    if not enabled or roles.get('chat', 'auto') != 'auto':
        return 'chat'
    latest = next((message.get('content') for message in reversed(messages)
                   if message.get('role') == 'user'), '')
    if not isinstance(latest, str):
        return 'chat'  # The established vision router owns multimodal requests.
    text = latest.casefold()
    coding = re.search(r'```|\b(?:php|javascript|typescript|python|refactor\w*|debug\w*|bugfix\w*|unit.?tests?|stacktrace|code review)\b', text)
    reasoning = re.search(r'\b(?:beweise|beweis|prove|proof|herleitung|reason step by step|mehrstufig|multi.step)\b', text)
    role = 'coding' if coding else 'agent' if reasoning else 'chat'
    return role if role in available_roles else 'chat'
