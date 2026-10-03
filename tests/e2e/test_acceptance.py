"""Acceptance actions go through browser UI and the production web/Agent boundary."""
import re

import pytest
from playwright.sync_api import expect


def send(page, prompt='Hello acceptance'):
    page.locator('#input').fill(prompt)
    page.locator('#sendButton').click()


def chat(page, agent):
    send(page)
    expect(page.locator('.message.assistant .message-content').last).to_contain_text(agent.answer)
    expect(page.locator('.mlx-message-speech-button').last).to_be_visible()


def speech(page):
    return page.locator('.mlx-message-speech-button').last


def open_sidebar(page):
    if page.locator('#sidebarToggle').is_visible() and not page.locator('#newChat').is_visible():
        page.locator('#sidebarToggle').click()


def test_chat_stream_actions_sessions(ui):
    page, agent, _ = ui
    agent.stream_gate.clear()
    send(page)
    expect(page.locator('.message.assistant .message-content')).to_contain_text('Acceptance streaming')
    assert 'complete.' not in page.locator('.message.assistant').inner_text()
    assert agent.terminals == 0
    agent.stream_gate.set()
    expect(page.locator('.message.assistant .message-content')).to_contain_text(agent.answer)
    expect(page.locator('#sendButton')).not_to_have_class(re.compile('stop'))
    assert agent.terminals == 1
    page.locator('.message.assistant [aria-label="Kopieren"]').click()
    assert page.evaluate('navigator.clipboard.readText()') == agent.answer
    page.locator('.message-info-btn').click()
    expect(page.locator('.message-info-tooltip')).to_be_attached()
    page.locator('.message.assistant button[aria-label="Neu generieren"], .message.assistant button[aria-label="Regenerate"]').click()
    expect(page.locator('.message.assistant .message-content')).to_contain_text(agent.answer)
    page.wait_for_function('!document.querySelector("#sendButton").classList.contains("stop")')
    assert agent.count('/api/runtime/chat/stream', 'POST') == 2
    open_sidebar(page)
    page.locator('#newChat').click()
    expect(page.locator('.message.assistant')).to_have_count(0)
    open_sidebar(page)
    page.locator('.chat-entry').filter(has_text='Hello acceptance').first.click()
    expect(page.locator('.message.assistant')).to_have_count(1)


# Only the CI media layer is controlled: real Audio instances, Fetch, Blob and URLs remain.
MEDIA = """() => {
    window.__media = {plays: 0, pauses: 0, revoked: [], audios: []};
    const NativeAudio = window.Audio;
    window.Audio = function(...args) {
        const audio = new NativeAudio(...args);
        window.__media.audios.push(audio);
        return audio;
    };
    window.Audio.prototype = NativeAudio.prototype;
    HTMLMediaElement.prototype.play = function() {
        window.__media.plays++;
        Object.defineProperty(this, 'paused', {value:false, configurable:true});
        this.dispatchEvent(new Event('playing'));
        return Promise.resolve();
    };
    HTMLMediaElement.prototype.pause = function() {
        window.__media.pauses++;
        Object.defineProperty(this, 'paused', {value:true, configurable:true});
        this.dispatchEvent(new Event('pause'));
    };
    const revoke = URL.revokeObjectURL.bind(URL);
    URL.revokeObjectURL = url => {window.__media.revoked.push(url); revoke(url);};
}"""


def test_read_aloud_paint_play_pause_resume_end(ui):
    page, agent, _ = ui
    chat(page, agent)
    page.evaluate(MEDIA)
    speech(page).click()
    # Hold the downstream response: verify state on the very next animation frame.
    state = page.evaluate('''() => new Promise(resolve => requestAnimationFrame(() => {
        const b = document.querySelector('.mlx-message-speech-button');
        resolve({busy:b.getAttribute('aria-busy'), state:b.dataset.speechState,
                 spinning:getComputedStyle(b.querySelector('svg')).animationName});
    }))''')
    assert state == {'busy': 'true', 'state': 'generating', 'spinning': 'mlx-assistant-speech-spin'}
    expect(page.locator('.mlx-message-speech-status')).to_contain_text(re.compile('generating|generiert|Generierung'))
    agent.speech_gate.set()
    expect(speech(page)).to_have_attribute('data-speech-state', 'playing')
    assert agent.count('/api/mlx/audio/speech', 'POST') == 1
    assert page.evaluate('window.__media.audios[0].src.startsWith("blob:")')
    speech(page).click()
    expect(speech(page)).to_have_attribute('data-speech-state', 'paused')
    speech(page).click()
    expect(speech(page)).to_have_attribute('data-speech-state', 'playing')
    assert page.evaluate('window.__media.plays') == 2
    page.evaluate('window.__media.audios[0].dispatchEvent(new Event("ended"))')
    expect(speech(page)).to_have_attribute('data-speech-state', 'idle')
    assert page.evaluate('window.__media.revoked.length') == 1
    assert page.evaluate('window.__media.audios[0].getAttribute("src")') is None
    assert agent.count('/api/mlx/audio/speech', 'POST') == 1


@pytest.mark.parametrize('language', ['de', 'en'])
def test_read_aloud_survives_same_session_refresh(ui, language):
    page, agent, _ = ui
    chat(page, agent)
    expect(page.locator('#sendButton')).not_to_have_class(re.compile('stop'))
    with page.expect_response(f'**/i18n/assistant-read-aloud.{language}.json') as dictionary:
        page.evaluate('(language) => window.MLXI18n.setLanguage(language)', language)
    dictionary.value.finished()
    page.evaluate(MEDIA)
    speech(page).click()
    expect(speech(page)).to_have_attribute('aria-busy', 'true')
    page.evaluate('window.__originalSpeechButton = document.querySelector(".mlx-message-speech-button")')
    page.evaluate('window.MLXChatSessions.syncWithServer()')
    assert page.evaluate('window.__originalSpeechButton !== document.querySelector(".mlx-message-speech-button")')
    expect(speech(page)).to_have_attribute('aria-busy', 'true')
    expect(speech(page)).to_have_attribute('data-speech-state', 'generating')
    expect(page.locator('.mlx-message-speech-status')).to_contain_text('erzeugt' if language == 'de' else 'generating')
    assert page.locator('.mlx-message-speech-button svg').evaluate('(svg) => getComputedStyle(svg).animationName') == 'mlx-assistant-speech-spin'
    agent.speech_gate.set()
    expect(speech(page)).to_have_attribute('data-speech-state', 'playing')
    page.evaluate('window.MLXChatRendering.renderMessages()')
    expect(speech(page)).to_have_attribute('data-speech-state', 'playing')
    speech(page).click()
    expect(speech(page)).to_have_attribute('data-speech-state', 'paused')
    page.evaluate('window.MLXChatSessions.syncWithServer()')
    expect(speech(page)).to_have_attribute('data-speech-state', 'paused')
    speech(page).click()
    expect(speech(page)).to_have_attribute('data-speech-state', 'playing')
    assert page.evaluate('window.__media.audios.length') == 1
    assert agent.count('/api/mlx/audio/speech', 'POST') == 1
    page.evaluate('window.__media.audios[0].dispatchEvent(new Event("ended"))')
    expect(speech(page)).to_have_attribute('data-speech-state', 'idle')
    assert page.evaluate('window.__media.revoked.length') == 1
    assert page.evaluate('window.__media.audios[0].getAttribute("src")') is None


@pytest.mark.parametrize('scenario', ['stop', 'second', 'rerender', 'removed', 'http', 'timeout', 'invalid'])
def test_read_aloud_cleanup_and_failures(ui, scenario):
    page, agent, allowed = ui
    chat(page, agent)
    if scenario == 'second':
        send(page, 'Second message')
        expect(page.locator('.mlx-message-speech-button')).to_have_count(2)
        expect(page.locator('#sendButton')).not_to_have_class(re.compile('stop'))
    if scenario == 'timeout':
        allowed.append('[assistant-read-aloud] AbortError: Speech request aborted')
        page.clock.install()
    if scenario != 'invalid':
        page.evaluate(MEDIA)
    if scenario == 'http':
        agent.speech_mode = 'http'
        allowed.extend(['503 (Service Unavailable)', 'Fixture speech unavailable'])
    if scenario == 'invalid':
        allowed.append('[assistant-read-aloud] Error: Audio playback failed')
        agent.speech_mode = 'invalid'
    initial = page.locator('.mlx-message-speech-button').first if scenario == 'second' else speech(page)
    initial.click()
    expect(initial).to_have_attribute('data-speech-state', 'generating')
    if scenario == 'stop':
        speech(page).click()
    elif scenario == 'second':
        speech(page).click()
        expect(page.locator('.mlx-message-speech-button').first).to_have_attribute('data-speech-state', 'idle')
        speech(page).click()
    elif scenario == 'rerender':
        open_sidebar(page)
        page.locator('#newChat').click()
    elif scenario == 'removed':
        page.locator('.mlx-message-speech-button').evaluate('(button) => button.remove()')
    elif scenario == 'timeout':
        page.clock.fast_forward(60001)
    else:
        agent.speech_gate.set()
    if scenario in ('http', 'timeout', 'invalid'):
        expect(speech(page)).to_have_attribute('data-speech-state', 'idle')
        expect(page.locator('.mlx-message-speech-status')).to_have_class(re.compile('is-error'))
    elif scenario == 'stop':
        expect(speech(page)).to_have_attribute('data-speech-state', 'idle')
    # An animation frame can still execute after DOM cleanup (observer must not loop).
    assert page.evaluate('() => new Promise(r => requestAnimationFrame(() => r(true)))')
    assert agent.count('/api/mlx/audio/speech', 'POST') <= (2 if scenario == 'second' else 1)


def media_start(page, prompt, profile=None):
    send(page, ('Generate a video: ' if 'ball' in prompt else 'Generate an image: ') + prompt)
    expect(page.locator('#mediaQualityModal')).to_be_visible()
    if profile:
        page.locator('#videoProfile').select_option(profile)
    page.locator('#mediaQualityModalConfirm').click()


def test_image_job_preview_download(ui):
    page, agent, _ = ui
    media_start(page, 'A red ceramic mug on a wooden table')
    expect(page.locator('.image-job-card')).to_be_visible()
    expect(page.locator('.image-job-card')).to_contain_text(re.compile('Lad|Loading|Gener|Erzeug'))
    image = page.locator('.image-artifact-preview')
    expect(image).to_be_visible()
    image.evaluate('(img) => img.decode()')
    assert image.evaluate('(img) => img.naturalWidth > 0 && img.naturalHeight > 0')
    expect(page.locator('.image-artifact-card a[href*="download=1"]')).to_be_visible()
    image.click()
    expect(page.locator('.image-preview-dialog')).to_be_visible()
    page.locator('.image-preview-dialog button').click()
    expect(page.locator('.image-preview-dialog')).not_to_be_visible()
    assert [j['status'] for j in agent.jobs.values()] == ['completed']


@pytest.mark.parametrize('available', [False, True])
def test_video_profile_progress_controls(ui, available):
    page, agent, _ = ui
    agent.uncensored = available
    send(page, 'Generate a video: A red ball rolling across a white table')
    expect(page.locator('#mediaQualityModal')).to_be_visible()
    option = page.locator('#videoProfile option[value="uncensored"]')
    expect(option).to_have_js_property('disabled', not available)
    expect(page.locator('#videoProfile')).to_have_value('standard')
    if available:
        page.locator('#videoProfile').select_option('uncensored')
    page.evaluate(MEDIA)
    page.locator('#mediaQualityModalConfirm').click()
    expect(page.locator('.video-job-card')).to_be_visible()
    expect(page.locator('.video-job-card')).to_contain_text(re.compile('Lad|Loading'))
    expect(page.locator('.video-job-card')).to_contain_text(re.compile('Gener|Erzeug'))
    player = page.locator('.video-artifact-player')
    expect(player).to_be_visible()
    assert player.evaluate('(video) => video.controls && Boolean(video.src)')
    player.evaluate('(video) => video.play()')
    assert page.evaluate('window.__media.plays') == 1
    player.evaluate('(video) => video.pause()')
    player.evaluate('(video) => video.play()')
    assert page.evaluate('window.__media.plays') == 2
    expect(page.locator('.video-artifact-card a[href*="download=1"]')).to_be_visible()
    action = next(body for method, path, body in agent.calls if path == '/api/chat/actions')
    assert action['video_options']['profile'] == ('uncensored' if available else 'standard')


def test_video_cancel_stops_polling_and_retains_revision(ui):
    page, agent, _ = ui
    agent.hold_jobs = True
    media_start(page, 'A red ball rolling across a white table')
    expect(page.locator('.video-job-card')).to_contain_text(re.compile('Gener|Erzeug'))
    job_id = next(iter(agent.jobs))
    before = next(iter(agent.chats.values()))['revision']
    page.locator('.video-job-card button').click()
    expect(page.locator('.video-job-card')).to_contain_text(re.compile('abgebrochen|cancelled'))
    path = '/api/video/jobs/' + job_id
    # One already in-flight poll may complete; wait past two polling intervals.
    page.wait_for_timeout(1100)
    polls = agent.count(path, 'GET')
    page.wait_for_timeout(1200)
    assert agent.count(path, 'GET') == polls
    assert agent.count(path + '/cancel', 'POST') == 1
    assert len(agent.jobs) == 1
    assert agent.jobs[job_id]['status'] == 'cancelled'
    assert before == next(iter(agent.chats.values()))['revision']
    expect(page.locator('.video-artifact-card')).to_have_count(0)
    expect(page.locator('.video-job-card button')).to_have_count(0)


def test_settings_models_runtime_storage_downloads(ui):
    page, agent, _ = ui
    page.clock.install()
    open_sidebar(page)
    page.get_by_role('button', name='Settings', exact=True).click()
    page.locator('button[data-organizer-section="models"]').click()
    page.locator('[data-organizer-model-tab="runtime"]').click()
    expect(page.locator('#modelConsoleContent')).to_have_attribute('aria-busy', 'false')
    expect(page.locator('#modelConsoleContent')).to_contain_text('Qwen')
    details = page.locator('#modelConsoleContent details').first
    expect(details).to_be_visible()
    assert not details.evaluate('(d) => d.open')
    details.locator('summary').click()
    expect(details).to_have_attribute('open', '')
    details.locator('summary').click()
    assert not details.evaluate('(d) => d.open')
    # Keep the real downstream response pending while the user interacts.
    for opened, pid, periodic in [(True, 2345, False), (False, 3456, False), (True, 4567, True)]:
        agent.model_system_entered.clear()
        agent.model_system_gate.clear()
        agent.model_pid = pid
        try:
            if periodic:
                page.clock.run_for(15000)
            else:
                page.evaluate('void window.MLXModelConsole.load({force: true})')
            assert agent.model_system_entered.wait(5), 'Runtime refresh did not reach Agent'
            expect(page.locator('#modelConsoleContent')).to_have_attribute('aria-busy', 'true')
            expect(details).to_be_visible()
            if details.evaluate('(d) => d.open') is not opened:
                details.locator('summary').click()
            assert details.evaluate('(d) => d.open') is opened
        finally:
            agent.model_system_gate.set()
        expect(page.locator('#modelConsoleContent')).to_contain_text(str(pid))
        assert details.evaluate('(d) => d.open') is opened
        expect(page.locator('#modelConsoleContent')).to_have_attribute('aria-busy', 'false')
    page.locator('[data-organizer-model-tab="storage"]').click()
    expect(page.locator('#modelConsoleContent')).to_contain_text('64')
    page.locator('[data-organizer-model-tab="downloads"]').click()
    expect(page.locator('#modelConsoleContent .model-console-empty')).to_be_visible()


def test_image_count_gallery_selection(ui):
    page, agent, _ = ui
    send(page, 'Generate an image: A red ceramic mug on a wooden table')
    expect(page.locator('#mediaQualityModal')).to_be_visible()
    page.locator('#imageVariantCount').select_option('2')
    page.locator('#mediaQualityModalConfirm').click()
    gallery = page.locator('.image-variant-gallery')
    expect(gallery).to_be_visible(timeout=10000)
    expect(gallery.locator('.image-variant-preview')).to_have_count(2)
    for image in gallery.locator('.image-variant-preview').all():
        image.evaluate('(img) => img.decode()')
        assert image.evaluate('(img) => img.naturalWidth > 0 && img.naturalHeight > 0')
    gallery.locator('.image-variant-slot').last.get_by_role('button', name='Use', exact=True).click()
    expect(gallery.locator('.image-variant-slot').last).to_have_class(re.compile('is-selected'))
    assert agent.count('/api/image/jobs/variants', 'POST') == 1
    assert len(agent.jobs) == 2


def test_read_aloud_one_request_per_chunk(ui):
    page, agent, _ = ui
    agent.answer = 'Acceptance streaming ' + 'This is a deterministic sentence for speech chunking. ' * 18
    chat(page, agent)
    page.evaluate(MEDIA)
    agent.speech_gate.set()
    speech(page).click()
    observed = 0
    for _ in range(6):
        expect(speech(page)).to_have_attribute('data-speech-state', 'playing')
        page.wait_for_function('(n) => window.__media.audios.length > n', arg=observed)
        observed += 1
        page.evaluate('window.__media.audios.at(-1).dispatchEvent(new Event("ended"))')
        page.wait_for_function('''(n) => document.querySelector('.mlx-message-speech-button').dataset.speechState === 'idle'
                                 || window.__media.audios.length > n''', arg=observed)
        if speech(page).get_attribute('data-speech-state') == 'idle':
            break
    assert observed > 1
    expect(speech(page)).to_have_attribute('data-speech-state', 'idle')
    requests = [body['input'] for method, path, body in agent.calls if path == '/api/mlx/audio/speech']
    assert len(requests) == observed
    assert ' '.join(requests) == agent.answer.strip()
    assert page.evaluate('window.__media.revoked.length') == observed


@pytest.mark.parametrize('scenario', ['second', 'rerender', 'removed'])
def test_read_aloud_playback_cleanup(ui, scenario):
    page, agent, _ = ui
    chat(page, agent)
    if scenario == 'second':
        send(page, 'Second message')
        expect(page.locator('.mlx-message-speech-button')).to_have_count(2)
        expect(page.locator('#sendButton')).not_to_have_class(re.compile('stop'))
    page.evaluate(MEDIA)
    agent.speech_gate.set()
    page.locator('.mlx-message-speech-button').first.click()
    expect(page.locator('.mlx-message-speech-button').first).to_have_attribute('data-speech-state', 'playing')
    if scenario == 'second':
        speech(page).click()
        expect(speech(page)).to_have_attribute('data-speech-state', 'playing')
        expect(page.locator('.mlx-message-speech-button').first).to_have_attribute('data-speech-state', 'idle')
    elif scenario == 'rerender':
        open_sidebar(page)
        page.locator('#newChat').click()
    else:
        page.locator('.mlx-message-speech-button').evaluate('(button) => button.remove()')
    page.wait_for_function('window.__media.revoked.length === 1')
    assert page.evaluate('window.__media.audios[0].getAttribute("src")') is None
    assert page.evaluate('window.__media.pauses') >= 1
