import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/model-scout-v3.js', import.meta.url), 'utf8'
);

function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
}

const response = data => ({ ok: true, json: async () => data });

function node(tag = 'div') {
    const value = {
        tagName: tag.toUpperCase(),
        dataset: {},
        children: [],
        textContent: '',
        innerHTML: '',
        append(...children) { this.children.push(...children); },
        appendChild(child) { this.children.push(child); return child; },
        addEventListener() {},
        querySelector(selector) {
            const match = /^\\[data-([a-z-]+)\\]$/.exec(selector);
            if (!match) return null;
            const key = match[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
            const queue = [...this.children];
            while (queue.length) {
                const entry = queue.shift();
                if (entry.dataset?.[key] !== undefined) return entry;
                queue.push(...(entry.children || []));
            }
            return null;
        },
        querySelectorAll() { return []; }
    };
    return value;
}

function panel(role = 'all') {
    const value = node('section');
    value.isConnected = true;
    const roleControl = { value: role };
    const query = value.querySelector.bind(value);
    value.querySelector = selector => {
        if (selector === '[data-scout-role]') return roleControl;
        if (selector === '.model-scout-controls' || selector === '[data-scout-grid]') return null;
        return query(selector);
    };
    return value;
}

async function settle() {
    for (let i = 0; i < 15; i++) await Promise.resolve();
}

test('Model Scout v3 mounts only once and rejects stale panel/locale refreshes', async () => {
    const events = new Map();
    const frameQueue = [];
    const calls = [];
    const observers = [];
    let active = panel();
    let language = 'en';
    let benchmarkData = [];
    let deferredDiscovery = null;
    const slowEnglish = deferred();

    class MutationObserverStub {
        constructor(callback) { this.callback = callback; observers.push(this); }
        observe() {}
        disconnect() {}
    }

    const document = {
        readyState: 'complete',
        documentElement: {},
        head: { appendChild() {} },
        addEventListener(name, callback) { events.set(name, callback); },
        querySelector(selector) {
            return selector === '#modelConsoleContent > .model-scout' ? active : null;
        },
        getElementById() { return {}; },
        createElement: node
    };
    const storage = new Map();
    const window = {
        MLXI18n: { getLocale: () => language }
    };
    window.window = window;

    const fetch = url => {
        calls.push(url);
        if (url === '/i18n/model-scout.en.json') return slowEnglish.promise;
        if (url === '/i18n/model-scout.de.json') {
            return Promise.resolve(response({ history_title: 'Benchmark-Verlauf' }));
        }
        if (url.startsWith('/api/mlx/model-scout/discover?')) {
            if (deferredDiscovery) {
                const pending = deferredDiscovery;
                deferredDiscovery = null;
                return pending.promise;
            }
            return Promise.resolve(response({ candidates: [] }));
        }
        if (url === '/api/mlx/model-scout/benchmarks') {
            return Promise.resolve(response({ benchmarks: benchmarkData }));
        }
        throw new Error('Unexpected network request: ' + url);
    };

    const context = {
        window, document, fetch, MutationObserver: MutationObserverStub,
        navigator: { language: 'en-US' },
        localStorage: {
            getItem(key) { return storage.get(key) ?? null; },
            setItem(key, value) { storage.set(key, String(value)); }
        },
        requestAnimationFrame(callback) { frameQueue.push(callback); },
        setTimeout, clearTimeout, console, Intl, Date
    };
    vm.runInNewContext(source, context, { filename: 'model-scout-v3.js' });

    const flushFrames = () => {
        const pending = frameQueue.splice(0);
        for (const callback of pending) callback();
    };
    const count = part => calls.filter(call => call.includes(part)).length;
    const rootObserver = observers[0];
    assert.ok(rootObserver, 'Root observer must be installed');

    flushFrames();
    for (let i = 0; i < 8; i++) rootObserver.callback();
    flushFrames();
    await settle();
    assert.equal(count('/i18n/model-scout.en.json'), 1);
    assert.equal(count('/model-scout/discover?'), 0);

    slowEnglish.resolve(response({ history_title: 'Benchmark history' }));
    await settle();
    assert.equal(count('/model-scout/discover?'), 1);
    assert.equal(count('/model-scout/benchmarks'), 1);
    assert.equal(active.dataset.scoutV3Wired, 'true');

    for (let i = 0; i < 8; i++) rootObserver.callback();
    flushFrames();
    await settle();
    assert.equal(count('/model-scout/discover?'), 1);
    assert.equal(count('/i18n/model-scout.en.json'), 1);

    const [first, second] = [
        window.MLXModelScoutV3.refresh(), window.MLXModelScoutV3.refresh()
    ];
    await Promise.all([first, second]);
    assert.equal(count('/model-scout/discover?'), 2, 'Concurrent refreshes share discovery');
    assert.equal(count('/model-scout/benchmarks'), 2, 'Concurrent refreshes share history');

    language = 'de';
    events.get('mlx-language-changed')();
    await settle();
    assert.equal(count('/i18n/model-scout.de.json'), 1);
    assert.match(active.querySelector('[data-scout-history-title]').textContent, /Benchmark-Verlauf/);

    benchmarkData = [{ candidate_repo: 'old-model' }];
    const oldGate = deferred();
    deferredDiscovery = oldGate;
    const oldRefresh = window.MLXModelScoutV3.refresh();
    await settle();

    const previousPanel = active;
    active = panel('coding');
    previousPanel.isConnected = false;
    benchmarkData = [{ candidate_repo: 'new-model' }];
    rootObserver.callback();
    flushFrames();
    await settle();

    assert.equal(active.dataset.scoutV3Wired, 'true');
    assert.equal(window.MLXModelScoutV3.latestBenchmarkFor({ id: 'new-model' })?.candidate_repo, 'new-model');

    oldGate.resolve(response({ candidates: [{ id: 'old-model' }] }));
    await oldRefresh;
    await settle();
    assert.equal(window.MLXModelScoutV3.latestBenchmarkFor({ id: 'new-model' })?.candidate_repo, 'new-model',
        'Stale previous-panel responses must not replace live history');
    assert.equal(count('/i18n/model-scout.de.json'), 1, 'Replacement reuses translation');
    assert.equal(count('/model-scout/discover?'), 4);
});
