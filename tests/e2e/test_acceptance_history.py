"""Real runner history boundary against the production UI and isolated Agent fixture."""
import copy
from types import SimpleNamespace

from playwright.sync_api import expect

from tests.acceptance.runner import Acceptance


def test_real_browser_acceptance_isolates_legacy_history(ui, web, tmp_path):
    page, agent, _ = ui
    url, _ = web
    # The ui fixture already opened the app. Establish the regression inventory
    # before opening the real runner's separate, fresh browser profile.
    page.goto('about:blank')
    def chat(chat_id, title, messages):
        return {'id': chat_id, 'title': title, 'created': 1, 'updated': 2,
                'revision': 3, 'messages': messages, 'settings': {}}
    foreign = {
        'normal': chat('normal', 'Normal', [{'role': 'user', 'content': 'fixture user'}]),
        'de-empty': chat('de-empty', 'Neuer Chat', []),
        'en-empty': chat('en-empty', 'New chat', []),
        'assistant-only': chat('assistant-only', 'Reply with exactly this',
                               [{'role': 'assistant', 'content': 'fixture assistant'}]),
    }
    agent.chats = copy.deepcopy(foreign)
    args = SimpleNamespace(url=url, chat_timeout=90, tts_timeout=90, image_timeout=300, video_timeout=360)
    acceptance = Acceptance(args)
    acceptance.root = tmp_path
    acceptance.browser = page.context.browser
    acceptance.initial_foreign_history = acceptance.foreign_history()
    agent.speech_gate.set()
    acceptance.speech_ready = lambda: None  # Fixture speech service, no model setup.
    try:
        # Uses the real runner's open_chat and native Chromium Audio playback.
        acceptance.tts_playback()
        image_job = {'id': 'a' * 24, 'kind': 'image', 'status': 'completed', 'prompt': 'fixture',
                     'chat_id': acceptance.chat_id}
        agent.jobs[image_job['id']] = image_job
        acceptance.image_result = agent.result(image_job)
        acceptance.image_preview()
        video_job = dict(image_job, id='b' * 24, kind='video')
        agent.jobs[video_job['id']] = video_job
        video = agent.result(video_job)
        browser_page = acceptance.open_chat([{'role': 'assistant', 'content': '', 'tool_result': video,
                                             'video_job': video_job}])
        expect(browser_page.locator('.video-artifact-player')).to_be_visible()
        # The fixture video is intentionally not a codec fixture. Native video
        # playback is checked against the real service by test-real.
        visible_ids = browser_page.evaluate('JSON.parse(localStorage.getItem("mlx-web-chats-v1")).map(c => c.id)')
        assert visible_ids == [acceptance.chat_id]
        browser_page.evaluate('window.MLXChatSessions.syncWithServer()')
        assert acceptance.foreign_history() == foreign
        acceptance.finish_browser('video')
        assert len(acceptance.history_checks) == 3
        assert all(row['identical'] for row in acceptance.history_checks)
        assert not acceptance.history_violations
        assert set(agent.chats) == set(foreign) | {acceptance.chat_id}
        acceptance.browser = None  # The shared browser belongs to the fixture.
        acceptance.cleanup()
        assert agent.chats == foreign
        assert not any(method == 'DELETE' and path != '/api/chats/' + acceptance.chat_id
                       for method, path, _ in agent.calls)
    finally:
        if acceptance.context:
            acceptance.context.close()
        acceptance.client.close()
