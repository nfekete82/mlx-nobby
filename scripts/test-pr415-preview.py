#!/usr/bin/env python3
"""Chromium persistence checks against the isolated localhost:8097 preview only.

Run with the CPU test environment: python scripts/test-pr415-preview.py
Uses fresh synthetic chats and a fresh browser context, never production data.
"""
import json
import uuid

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8097"
PREFIX = "pr415-" + uuid.uuid4().hex

BOOT = """async (loadCache) => {
    window.testState = { sessions: [], activeId: null };
    window.testGenerating = false;
    MLXChatSessions.configure({state: testState, renderAll() {}, renderSidebar() {},
        isGenerating: () => testGenerating, createSessionSettings: () => ({}),
        onSessionSelected() {}});
    if (loadCache) MLXChatSessions.loadSessions();
    await MLXChatSessions.syncWithServer();
}"""
EDIT = """async ({id, text}) => {
    const chat = testState.sessions.find(s => s.id === id);
    chat.updated = Math.max(Date.now(), chat.updated + 1);
    chat.messages.push({ role: 'assistant', content: text });
    await MLXChatSessions.persistSession(chat);
}"""


def boot(page, load_cache=False):
    page.goto(BASE + "/api/health")
    page.add_script_tag(url=BASE + "/assets/common.js")
    page.add_script_tag(url=BASE + "/assets/chat/sessions.js")
    page.evaluate(BOOT, load_cache)


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        # Every request remains on the preview origin.
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith(BASE + "/") else route.abort())
        for suffix in ["a", "b", "shared"]:
            chat_id = PREFIX + "-" + suffix
            response = context.request.put(BASE + "/api/mlx/chats/" + chat_id, data={
                "id": chat_id, "title": chat_id, "created": 1, "updated": 10,
                "messages": [{"role": "user", "content": PREFIX}],
                "expected_updated": -1,
            })
            assert response.ok, response.text()
        first, second = context.new_page(), context.new_page()
        boot(first)
        boot(second)

        def edit(page, suffix, text):
            page.evaluate(EDIT, {"id": PREFIX + "-" + suffix, "text": text})

        def chats():
            response = context.request.get(BASE + "/api/mlx/chats")
            assert response.ok
            return response.json()["chats"]

        def has_text(chat, text):
            return any(m.get("content") == text for m in chat["messages"])

        edit(first, "a", PREFIX + "-separate-A")
        edit(second, "b", PREFIX + "-separate-B")
        second.evaluate("MLXChatSessions.saveSessions()")
        second.wait_for_timeout(100)
        saved = chats()
        assert any(has_text(c, PREFIX + "-separate-A") for c in saved)
        assert any(has_text(c, PREFIX + "-separate-B") for c in saved)
        print("PASS 1: separate chats remain durable")

        edit(first, "shared", PREFIX + "-winner")
        edit(second, "shared", PREFIX + "-conflicting-draft")
        saved = chats()
        winner = next(c for c in saved if c["id"] == PREFIX + "-shared")
        copies = [c for c in saved if c["id"] != winner["id"] and
                  has_text(c, PREFIX + "-conflicting-draft")]
        assert has_text(winner, PREFIX + "-winner")
        assert len(copies) == 1, "Rejected tab B edit was not persisted exactly once"
        boot(second, True)
        assert sum(has_text(c, PREFIX + "-conflicting-draft") for c in chats()) == 1
        print("PASS 2: conflicting versions survive reload under distinct IDs")

        boot(first)
        boot(second)
        edit(first, "shared", PREFIX + "-generation-winner")
        second.evaluate("testGenerating = true")
        edit(second, "shared", PREFIX + "-generation-draft")
        second.evaluate("MLXChatSessions.saveSessions()")
        first.evaluate("MLXChatSessions.saveSessions()")  # replace shared list cache
        boot(second, True)
        assert sum(has_text(c, PREFIX + "-generation-draft") for c in chats()) == 1
        print("PASS 3: generating conflict survives another tab's cache write and reload")

        boot(first)
        boot(second)
        edit(first, "shared", PREFIX + "-identical")
        edit(second, "shared", PREFIX + "-identical")
        assert sum(has_text(c, PREFIX + "-identical") for c in chats()) == 1
        print("PASS 4: identical concurrent content creates no copy")
        boot(first)
        boot(second)
        third = context.new_page()
        boot(third)
        edit(first, "shared", PREFIX + "-third-tab-winner")
        edit(second, "shared", PREFIX + "-same-losing-draft")
        edit(third, "shared", PREFIX + "-same-losing-draft")
        assert sum(has_text(c, PREFIX + "-same-losing-draft") for c in chats()) == 1
        print("PASS 5: identical losing tabs converge on one conflict copy")

        for page in [first, second, third]:
            boot(page)
        edit(first, "shared", PREFIX + "-three-tab-winner")
        edit(second, "shared", PREFIX + "-distinct-B")
        edit(third, "shared", PREFIX + "-distinct-C")
        saved = chats()
        b = [c for c in saved if has_text(c, PREFIX + "-distinct-B")]
        c = [c for c in saved if has_text(c, PREFIX + "-distinct-C")]
        assert len(b) == len(c) == 1 and b[0]["id"] != c[0]["id"]
        print("PASS 6: three tabs retain three distinct versions")
        print(json.dumps({"origin": BASE, "fixture_prefix": PREFIX, "checks": 6}))
        context.close()
        browser.close()


if __name__ == "__main__":
    run()
