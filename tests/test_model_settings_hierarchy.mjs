import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

// Small DOM for rendering tests, with selectors used by the overview enhancer.
class Element {
    constructor(tag) {
        this.tagName = tag.toUpperCase();
        this.children = [];
        this.dataset = {};
        this.attributes = {};
        this.className = '';
        this.hidden = false;
        this.listeners = {};
        this.classList = {
            contains: name => this.className.split(' ').includes(name),
            add: name => { if (!this.classList.contains(name)) this.className += ' ' + name; },
            remove: name => { this.className = this.className.split(' ').filter(item => item !== name).join(' '); },
            toggle: (name, enabled) => enabled ? this.classList.add(name) : this.classList.remove(name),
        };
    }
    get childNodes() { return this.children; }
    get lastChild() { return this.children.at(-1); }
    get textContent() { return (this.text || '') + this.children.map(item => item.textContent).join(''); }
    set textContent(value) { this.text = String(value); this.children = []; }
    set innerHTML(value) { assert.equal(value, ''); this.text = ''; this.children = []; }
    appendChild(child) {
        if (child.tagName === '#FRAGMENT') { [...child.children].forEach(item => this.appendChild(item)); return child; }
        child.remove();
        child.parentElement = this;
        this.children.push(child);
        return child;
    }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    replaceChildren(...children) { this.children = []; this.text = ''; this.append(...children); }
    remove() {
        if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(item => item !== this);
        this.parentElement = null;
    }
    insertAdjacentElement(position, child) {
        assert.equal(position, 'afterend');
        child.remove();
        child.parentElement = this.parentElement;
        this.parentElement.children.splice(this.parentElement.children.indexOf(this) + 1, 0, child);
    }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(name, listener) { this.listeners[name] = listener; }
    querySelectorAll(selector) {
        const parts = selector.replaceAll(' > ', ' ').trim().split(/\s+/);
        const match = (element, part) => part.startsWith('.')
            ? element.classList.contains(part.slice(1)) : element.tagName === part.toUpperCase();
        const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);
        if (parts[0] === ':scope') return this.children.filter(child => match(child, parts[1]));
        const find = (element, index) => descendants(element).filter(child => match(child, parts[index]))
            .flatMap(child => index === parts.length - 1 ? [child] : find(child, index + 1));
        return find(this, 0);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function environment(language = 'en') {
    const catalog = JSON.parse(fs.readFileSync(`frontend/i18n/${language}.json`, 'utf8'));
    const content = new Element('div');
    const root = new Element('section');
    root.append(content);
    const document = {
        readyState: 'loading',
        head: new Element('head'),
        getElementById: id => id === 'modelConsoleContent' ? content : null,
        createElement: tag => new Element(tag),
        createTextNode: text => { const node = new Element('#text'); node.textContent = text; return node; },
        createDocumentFragment: () => new Element('#fragment'),
        addEventListener() {},
    };
    const window = { MLXI18n: {
        getLocale: () => language,
        t: (key, fallback) => {
            const value = key.split('.').reduce((entry, part) => entry?.[part], catalog);
            assert.equal(typeof value, 'string', `Missing ${language} translation: ${key}`);
            return value ?? fallback;
        },
    } };
    const context = { window, document, console, setTimeout, clearTimeout };
    let source = fs.readFileSync('frontend/assets/chat/models.js', 'utf8');
    source = source.replace('    window.MLXModelConsole = {', '    window.renderers = { renderRuntime, renderStorage, renderModels, renderDownloads };\n    window.MLXModelConsole = {');
    vm.runInNewContext(source, context);
    source = fs.readFileSync('frontend/assets/chat/model-overview.js', 'utf8');
    source = source.replace("    if (document.readyState === 'loading')", "    window.overview = { state, applyOverview, renderSummary };\n    if (document.readyState === 'loading')");
    vm.runInNewContext(source, context);
    const state = window.MLXModelConsole.__test.state;
    state.aliases = { current: 'owner/Qwen-4-bit', models: [
        { alias: 'z-qwen', repo: 'owner/Qwen-4-bit', active: true, backend: 'vlm', vision: true, quantization: '4-bit' },
        { alias: 'a-local', repo: '/example/Models/Alpha', local: true, backend: 'llm' },
        { alias: 'b-beta', repo: '/example/Models/Beta', local: true, backend: 'llm' },
    ] };
    state.status = { online: true, model: state.aliases.current, thinking: true };
    state.system = { mlx: { memory_mb: 2048, pid: 1234, port: 8000, uptime_seconds: 120, server_args: ['--model', 'owner/Qwen-4-bit'] }, system: { total_gb: 64, free_percent: 50 } };
    state.cache = { count: 1, total_size_bytes: 1024 ** 3, models: [{ repo: 'owner/Qwen-4-bit', complete: true, size_bytes: 1024 ** 3 }] };
    return { ...window.renderers, state, overview: window.overview, content };
}

for (const language of ['en', 'de']) {
    test(`${language}: runtime essentials once, technical details collapsed, actions retained`, () => {
        const env = environment(language);
        let runtime = env.renderRuntime();
        const hero = runtime.querySelector('.model-console-hero');
        const technical = runtime.querySelector('details');
        assert.equal(runtime.querySelectorAll('.model-console-status').length, 1);
        assert.equal(runtime.querySelectorAll('h5').length, 1);
        assert.equal(hero.querySelector('h5').textContent, 'Qwen');
        assert.equal(hero.querySelectorAll('.model-console-metric').length, 3);
        assert.equal(hero.querySelectorAll('.model-console-metric').filter(item => item.children[0].textContent === 'RAM').length, 1);
        assert.doesNotMatch(hero.textContent, /PID|1234/);
        assert.equal(technical.querySelectorAll('dt').filter(item => item.textContent === 'PID').length, 1);
        assert.ok(!technical.open);
        assert.deepEqual(technical.querySelectorAll('dt').map(item => item.textContent), [
            'PID', language === 'de' ? 'Server-Endpunkt' : 'Server endpoint', 'Repository', language === 'de' ? 'Startparameter' : 'Start parameters',
        ]);
        for (const action of ['restart-runtime', 'stop-runtime', 'show-logs', 'switch-selected-model', 'toggle-thinking']) {
            assert.equal(runtime.querySelectorAll('button').filter(item => item.dataset.action === action).length, 1);
        }
        const toggle = runtime.querySelectorAll('button').find(item => item.dataset.action === 'toggle-thinking');
        assert.equal(toggle.attributes['aria-pressed'], 'true');
        assert.equal(toggle.textContent, language === 'de' ? 'An' : 'On');
        env.state.status.online = false;
        runtime = env.renderRuntime();
        assert.equal(runtime.querySelectorAll('button').filter(item => item.dataset.action === 'start-runtime').length, 1);
        env.state.runtimeAction = { type: 'restart', phase: 'initializing' };
        assert.equal(env.renderRuntime().querySelectorAll('.model-console-action-progress').length, 1);
        env.state.aliases.models = [];
        env.state.status.model = 'owner/Unregistered-4-bit';
        assert.equal(env.renderRuntime().querySelector('h5').textContent, 'Unregistered');
    });

    test(`${language}: storage groups separate system memory from model storage`, () => {
        const storage = environment(language).renderStorage();
        const groups = storage.querySelectorAll('.model-console-storage-group');
        assert.equal(groups.length, 2);
        assert.equal(groups[0].querySelector('h5').textContent, 'System');
        assert.match(groups[0].textContent, /Unified Memory64 GB/);
        assert.match(groups[0].textContent, language === 'de' ? /RAM frei50 %/ : /Free RAM50 %/);
        assert.match(groups[1].textContent, /Hugging[- ]Face/);
        assert.match(groups[1].textContent, language === 'de' ? /HF-Modelle1/ : /HF models1/);
        assert.ok(storage.querySelectorAll('h5').every(item => !['Storage', 'Speicher'].includes(item.textContent)));
    });

    test(`${language}: adaptive overview counts, search, filter, sort and observer stability`, () => {
        const env = environment(language);
        env.content.append(env.renderModels());
        env.overview.applyOverview();
        const summary = env.content.querySelector('.model-overview-summary');
        const rows = () => env.content.querySelectorAll('.model-console-row');
        assert.equal(summary.children.length, 4);
        assert.match(summary.textContent, language === 'de' ? /3 installiert/ : /3 installed/);
        assert.match(summary.textContent, /1 Vision/);
        assert.match(summary.textContent, language === 'de' ? /2 lokal1 aktiv/ : /2 local1 active/);
        assert.equal(rows()[0].querySelector('strong').textContent, 'Qwen');
        const initialChip = summary.children[0];
        env.overview.applyOverview();
        assert.equal(summary.children[0], initialChip, 'unchanged summary does not mutate the DOM');
        env.overview.state.filter = 'vision';
        env.overview.applyOverview();
        assert.equal(rows().filter(row => !row.hidden).length, 1);
        assert.match(summary.textContent, language === 'de' ? /1 von 3 sichtbar/ : /1 of 3 visible/);
        env.overview.state.filter = 'all';
        env.overview.state.query = 'alpha';
        env.overview.applyOverview();
        assert.deepEqual(rows().filter(row => !row.hidden).map(row => row.querySelector('strong').textContent), ['Alpha']);
        env.overview.state.query = 'does-not-exist';
        env.overview.applyOverview();
        assert.ok(env.content.querySelector('.model-overview-empty'));
        env.overview.state.query = '   ';
        env.overview.state.sort = 'name';
        env.overview.applyOverview();
        assert.equal(summary.children.length, 4);
        assert.equal(env.content.querySelector('.model-overview-empty'), null);
        assert.deepEqual(rows().map(row => row.querySelector('strong').textContent), ['Alpha', 'Beta', 'Qwen']);
        env.overview.state.sort = 'alias';
        env.overview.applyOverview();
        assert.deepEqual(rows().map(row => row.querySelector('.model-console-alias').textContent), ['a-local', 'b-beta', 'z-qwen']);
        assert.equal(env.content.querySelectorAll('.model-console-metric').length, 0);
        assert.doesNotMatch(env.content.textContent, /Downloads/);
    });

    test(`${language}: downloads contain only jobs and a compact empty state`, () => {
        const env = environment(language);
        let downloads = env.renderDownloads();
        assert.equal(downloads.querySelectorAll('.model-console-empty').length, 1);
        assert.equal(downloads.querySelectorAll('.model-console-metric').length, 0);
        env.state.jobs = [{ id: 'job1', repo: 'owner/Qwen', status: 'running', progress: 0.5 }];
        downloads = env.renderDownloads();
        assert.match(downloads.textContent, /50 %/);
        assert.equal(downloads.querySelectorAll('.model-console-storage-row').length, 1);
    });
}


test('settings title ownership, content order and tab-specific visibility contracts', () => {
    const html = fs.readFileSync('frontend/chat.html', 'utf8');
    const layout = fs.readFileSync('frontend/assets/chat/settings-layout.js', 'utf8');
    const models = fs.readFileSync('frontend/assets/chat/models.js', 'utf8');
    const css = fs.readFileSync('frontend/assets/chat.css', 'utf8');
    const overview = fs.readFileSync('frontend/assets/chat/model-overview.js', 'utf8');
    const scout = fs.readFileSync('frontend/assets/chat/model-scout.js', 'utf8');
    assert.doesNotMatch(html + models, /modelConsoleTitle/);
    assert.match(layout, /setAttribute\('aria-labelledby', contentTitle.id\)/);
    assert.ok(html.indexOf('id="modelConsoleContent"') < html.indexOf('id="modelConsoleAssignments"'));
    assert.match(scout, /content.appendChild\(panel\)/);
    assert.match(models, /content.dataset.activeModelTab = state.activeTab/);
    assert.doesNotMatch(models, /content.dataset.modelConsoleTab/);
    assert.match(css, /model-console-secondary\[hidden\]\s*\{\s*display: none/);
    assert.match(css, /:not\(\[data-active-model-tab="models"\]\) > .model-scout\s*\{\s*display: none/);
    assert.match(overview, /model-console-row\[hidden\]\s*\{\s*display: none/);
});
