import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../frontend/assets/chat/assistant-read-aloud.js', import.meta.url), 'utf8');
const voiceSource = fs.readFileSync(new URL('../frontend/assets/chat/voice.js', import.meta.url), 'utf8');
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function classes() {
    const values = new Set();
    return { add: x => values.add(x), remove: x => values.delete(x), contains: x => values.has(x),
        toggle(x, on) { if (on) values.add(x); else values.delete(x); } };
}
function message(text, lang = '') {
    const status = { hidden: true, textContent: '', classList: classes() };
    const article = { lang, querySelector(selector) {
        if (selector === '.mlx-message-speech-status') return status;
        return { children: [{ tagName: 'DIV', className: '', cloneNode: () => ({ innerText: text, querySelectorAll: () => [] }) }] };
    } };
    const attributes = new Map();
    const button = { disabled: false, isConnected: true, innerHTML: 'speaker', dataset: {}, classList: classes(),
        closest: selector => selector === '.message.assistant' ? article : button,
        setAttribute: (k, v) => attributes.set(k, v), removeAttribute: k => attributes.delete(k),
        getAttribute: k => attributes.get(k) ?? null };
    return { button, article, status };
}
function harness({ audioMode = 'normal', lang = 'en', ignoreAbort = false } = {}) {
    const listeners = new Map(), timers = new Map(), requests = [], audios = [], revoked = [], errors = [];
    let nextTimer = 0, observer;
    const window = { MLXI18n: { getLanguage: () => lang }, MLXVoice: { getSettings: () => ({ voice: 'Serena', speed: 1 }) } };
    const document = { documentElement: { lang }, head: { appendChild() {} },
        getElementById: id => id === 'messagesInner' ? {} : null,
        createElement: () => ({}), addEventListener(name, fn) {
            const entries = listeners.get(name) || []; entries.push(fn); listeners.set(name, entries);
        } };
    class Audio {
        constructor(url) { this.url = url; this.paused = true; this.events = new Map(); this.plays = 0; audios.push(this); }
        addEventListener(name, fn) { const entries = this.events.get(name) || new Set(); entries.add(fn); this.events.set(name, entries); }
        removeEventListener(name, fn) { this.events.get(name)?.delete(fn); }
        emit(name) { for (const fn of [...(this.events.get(name) || [])]) fn(); }
        play() { this.plays++; if (audioMode === 'reject') return Promise.reject(Error('play rejected'));
            this.paused = false; if (audioMode === 'normal') this.emit('playing');
            return audioMode === 'pending' ? new Promise(() => {}) : Promise.resolve(); }
        pause() { this.paused = true; this.emit('pause'); }
        removeAttribute() { this.detached = true; }
        load() { this.released = true; }
    }
    const context = vm.createContext({ window, document, Audio, AbortController,
        console: { error: (...args) => errors.push(args) },
        URL: { createObjectURL: () => 'blob:' + audios.length, revokeObjectURL: url => revoked.push(url) },
        MutationObserver: class { constructor(fn) { observer = fn; } observe() {} },
        setTimeout(fn, delay) { const id = ++nextTimer; timers.set(id, { fn, delay }); return id; },
        clearTimeout: id => timers.delete(id),
        fetch(url, options) {
            if (!url.includes('/audio/speech')) return Promise.resolve({ ok: true, json: async () => ({}) });
            return new Promise((resolve, reject) => {
                const request = { options, body: JSON.parse(options.body), resolve, reject }; requests.push(request);
                if (!ignoreAbort) options.signal.addEventListener('abort', () => { const e = Error('aborted'); e.name = 'AbortError'; reject(e); });
            });
        }
    });
    vm.runInContext(source, context);
    const click = button => {
        const event = { target: button, preventDefault() {}, stopped: false, stopImmediatePropagation() { this.stopped = true; } };
        for (const fn of listeners.get('click') || []) { fn(event); if (event.stopped) break; }
    };
    const respond = (index = requests.length - 1, options = {}) => requests[index].resolve({ ok: true,
        blob: async () => ({ size: 10, type: 'audio/mpeg' }), ...options });
    const fireTimers = delay => { for (const [id, timer] of [...timers]) if (timer.delay === delay) { timers.delete(id); timer.fn(); } };
    return { window, context, listeners, click, requests, audios, revoked, timers, respond, fireTimers, mutate: () => observer(), errors };
}

test('click paints generating state immediately, stays cancellable, sends one POST and uses UI language', async () => {
    const h = harness(), m = message('Hello world.'); h.click(m.button);
    assert.equal(m.button.classList.contains('is-generating'), true);
    assert.equal(m.button.getAttribute('aria-busy'), 'true');
    assert.equal(m.button.disabled, false);
    assert.equal(m.button.dataset.speechState, 'generating');
    assert.match(m.button.innerHTML, /M12 3a9/);
    assert.match(m.status.textContent, /generating/);
    assert.equal(h.requests.length, 1); assert.equal(h.requests[0].options.method, 'POST');
    assert.equal(h.requests[0].body.language, 'en');
    h.window.MLXAssistantReadAloud.stop(); await flush();
});

test('success, pause/resume and ended restore the speaker and release URL/audio/listeners', async () => {
    const h = harness(), m = message('Hallo.', 'de'); h.click(m.button); h.respond(); await flush();
    assert.equal(h.requests[0].body.language, 'de');
    assert.equal(m.button.getAttribute('aria-busy'), null);
    assert.equal(m.button.dataset.speechState, 'playing'); assert.equal(h.audios[0].plays, 1);
    h.click(m.button); await flush(); assert.equal(m.button.dataset.speechState, 'paused');
    h.click(m.button); await flush(); assert.equal(m.button.dataset.speechState, 'playing'); assert.equal(h.audios[0].plays, 2);
    assert.equal(h.requests.length, 1);
    h.audios[0].emit('ended'); await flush();
    assert.equal(m.button.dataset.speechState, 'idle'); assert.equal(m.status.hidden, true);
    assert.equal(h.revoked.length, 1); assert.equal(h.audios[0].released, true);
    assert.equal(h.timers.size, 0); assert.ok([...h.audios[0].events.values()].every(set => set.size === 0));
});

test('HTTP error resets state and remains retryable', async () => {
    const h = harness(), m = message('Hello.'); h.click(m.button);
    h.respond(0, { ok: false, status: 503, json: async () => ({ detail: 'unavailable' }) }); await flush();
    assert.equal(m.button.dataset.speechState, 'idle'); assert.equal(m.button.getAttribute('aria-busy'), null);
    assert.equal(m.status.classList.contains('is-error'), true); assert.match(m.status.textContent, /failed/);
    h.click(m.button); assert.equal(h.requests.length, 2); h.window.MLXAssistantReadAloud.stop(); await flush();
});

test('generation timeout aborts request, resets and shows timeout', async () => {
    const h = harness(), m = message('Hello.'); h.click(m.button); h.fireTimers(60000); await flush();
    assert.equal(h.requests[0].options.signal.aborted, true); assert.equal(m.button.dataset.speechState, 'idle');
    assert.match(m.status.textContent, /timed out/); assert.equal(h.timers.size, 0);
});

test('second click during generation cancels and clears state', async () => {
    const h = harness(), m = message('Hello.'); h.click(m.button); h.click(m.button); await flush();
    assert.equal(h.requests.length, 1); assert.equal(h.requests[0].options.signal.aborted, true);
    assert.equal(m.button.dataset.speechState, 'idle'); assert.equal(m.status.hidden, true);
});

test('another message aborts the previous request and stops previous playback', async () => {
    const h = harness(), first = message('First.'), second = message('Second.');
    h.click(first.button); h.click(second.button); await flush();
    assert.equal(h.requests[0].options.signal.aborted, true); assert.equal(second.button.dataset.speechState, 'generating');
    h.respond(); await flush(); const previous = h.audios[0];
    h.click(first.button); await flush(); assert.equal(previous.released, true); assert.equal(h.revoked.length, 1);
    assert.equal(second.button.dataset.speechState, 'idle'); h.window.MLXAssistantReadAloud.stop(); await flush();
});

test('rerender/disconnected button cleans requests and playback', async () => {
    for (const playing of [false, true]) {
        const h = harness(), m = message('Hello.'); h.click(m.button);
        if (playing) { h.respond(); await flush(); }
        m.button.isConnected = false; h.mutate(); await flush();
        assert.equal(m.button.dataset.speechState, 'idle'); assert.equal(h.timers.size, 0);
        if (playing) assert.equal(h.audios[0].released, true);
        else assert.equal(h.requests[0].options.signal.aborted, true);
    }
});

test('duplicate script initialization retains one click handler and one POST', async () => {
    const h = harness(); vm.runInContext(source, h.context); await flush();
    assert.equal(h.listeners.get('click').length, 1);
    h.click(message('Hello.').button); assert.equal(h.requests.length, 1); h.window.MLXAssistantReadAloud.stop(); await flush();
});

test('empty assistant text makes no request', () => {
    const h = harness(), m = message('  '); h.click(m.button); assert.equal(h.requests.length, 0);
    assert.match(m.status.textContent, /No readable/); assert.equal(m.button.dataset.speechState, 'idle');
});

test('long answers request exactly one chunk at a time in order', async () => {
    const h = harness(), text = 'A complete sentence. '.repeat(100).trim(), m = message(text);
    const expected = h.window.MLXAssistantReadAloud.__test.splitSpeechText(text);
    h.click(m.button);
    for (let index = 0; index < expected.length; index++) {
        assert.equal(h.requests.length, index + 1); assert.equal(h.requests[index].body.input, expected[index]);
        h.respond(index); await flush(); assert.equal(h.requests.length, index + 1);
        h.audios[index].emit('ended'); await flush();
    }
    assert.equal(m.button.dataset.speechState, 'idle'); assert.equal(h.revoked.length, expected.length);
});

test('playback start watchdog handles both unresolved play and resolved play without playing event', async () => {
    for (const audioMode of ['pending', 'silent']) {
        const h = harness({ audioMode }), m = message('Hello.'); h.click(m.button); h.respond(); await flush();
        h.fireTimers(15000); await flush(); assert.equal(m.button.dataset.speechState, 'idle');
        assert.match(m.status.textContent, /could not start/); assert.equal(h.audios[0].released, true);
        assert.equal(h.timers.size, 0);
    }
});

test('normal long playback has no generation or start timer; audio errors and play rejection recover', async () => {
    const h = harness(), m = message('Hello.'); h.click(m.button); h.respond(); await flush();
    assert.equal(h.timers.size, 0); h.fireTimers(15000); h.fireTimers(60000);
    assert.equal(m.button.dataset.speechState, 'playing'); h.audios[0].emit('error'); await flush();
    assert.equal(m.button.dataset.speechState, 'idle'); assert.match(m.status.textContent, /failed/);
    const rejecting = harness({ audioMode: 'reject' }), other = message('Hello.');
    rejecting.click(other.button); rejecting.respond(); await flush();
    assert.equal(other.button.dataset.speechState, 'idle'); assert.equal(rejecting.revoked.length, 1);
});

test('language switch stops the active state', async () => {
    const h = harness(), m = message('Hello.'); h.click(m.button);
    for (const fn of h.listeners.get('mlx-language-changed')) fn(); await flush();
    assert.equal(h.requests[0].options.signal.aborted, true); assert.equal(m.button.dataset.speechState, 'idle');
});

test('voice status observer does not rewrite identical text or assistant-owned status', () => {
    const start = voiceSource.indexOf('    function syncSpeechStatuses()');
    const end = voiceSource.indexOf('    function extractAssistantText', start);
    const sync = voiceSource.slice(start, end);
    let writes = 0, text = 'Serena · playing';
    const node = { closest: () => null, get textContent() { return text; }, set textContent(value) { writes++; text = value; } };
    let label = 'Serena';
    const context = vm.createContext({ voiceLabel: () => label, FALLBACK_VOICES: [{ label: 'Serena' }], voices: [{ label: 'Laura' }],
        document: { querySelectorAll: () => [node] } });
    vm.runInContext(sync, context); vm.runInContext('syncSpeechStatuses()', context);
    assert.equal(writes, 0);
    label = 'Laura'; vm.runInContext('syncSpeechStatuses()', context); vm.runInContext('syncSpeechStatuses()', context);
    assert.equal(writes, 1);
    node.closest = () => ({}); label = 'Serena'; vm.runInContext('syncSpeechStatuses()', context);
    assert.equal(writes, 1);
});

test('cancel and immediately restart the same button cannot be reset by the old request', async () => {
    const h = harness(), m = message('Hello.');
    h.click(m.button); h.click(m.button); h.click(m.button); await flush();
    assert.equal(h.requests.length, 2); assert.equal(h.requests[0].options.signal.aborted, true);
    assert.equal(m.button.dataset.speechState, 'generating'); assert.equal(m.button.getAttribute('aria-busy'), 'true');
    h.respond(); await flush(); assert.equal(m.button.dataset.speechState, 'playing');
    h.window.MLXAssistantReadAloud.stop(); await flush();
});

test('resume rejection releases playback and leaves retryable idle state', async () => {
    const h = harness(), m = message('Hello.'); h.click(m.button); h.respond(); await flush();
    h.click(m.button); await flush(); h.audios[0].play = () => Promise.reject(Error('resume failed'));
    h.click(m.button); await flush();
    assert.equal(m.button.dataset.speechState, 'idle'); assert.equal(h.audios[0].released, true);
    assert.match(m.status.textContent, /failed/); assert.equal(h.timers.size, 0);
});

test('invalid or empty speech response resets before audio construction', async () => {
    for (const blob of [{ size: 0, type: 'audio/mpeg' }, { size: 10, type: 'text/html' }]) {
        const h = harness(), m = message('Hello.'); h.click(m.button); h.respond(0, { blob: async () => blob }); await flush();
        assert.equal(h.audios.length, 0); assert.equal(m.button.dataset.speechState, 'idle'); assert.match(m.status.textContent, /failed/);
    }
});


test('timeout remains effective when a shared fetch wrapper ignores the signal', async () => {
    const h = harness({ ignoreAbort: true }), m = message('Hello.');
    h.click(m.button); h.fireTimers(60000); await flush();
    assert.equal(m.button.dataset.speechState, 'idle'); assert.match(m.status.textContent, /timed out/);
    h.respond(); await flush(); assert.equal(h.audios.length, 0); assert.equal(h.timers.size, 0);
});
