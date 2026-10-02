import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';


class FakeClassList {
    constructor(values = []) {
        this.values = new Set(values);
    }

    add(...values) {
        values.forEach(value => this.values.add(value));
    }

    contains(value) {
        return this.values.has(value);
    }
}


class FakeElement {
    constructor(id = '', classes = []) {
        this.id = id;
        this.classList = new FakeClassList(classes);
        this.children = [];
        this.parentElement = null;
        this.style = { setProperty() {} };
        this.listeners = new Map();
        this.textContent = '';
    }

    get nextSibling() {
        if (!this.parentElement) return null;
        const siblings = this.parentElement.children;
        const index = siblings.indexOf(this);
        return index >= 0 ? siblings[index + 1] || null : null;
    }

    appendChild(child) {
        return this.insertBefore(child, null);
    }

    insertBefore(child, reference) {
        if (child.parentElement) {
            const oldSiblings = child.parentElement.children;
            const oldIndex = oldSiblings.indexOf(child);
            if (oldIndex >= 0) oldSiblings.splice(oldIndex, 1);
        }

        const index = reference ? this.children.indexOf(reference) : -1;
        if (index >= 0) this.children.splice(index, 0, child);
        else this.children.push(child);
        child.parentElement = this;
        return child;
    }

    addEventListener(type, listener) {
        this.listeners.set(type, listener);
    }

    click() {
        this.listeners.get('click')?.({ target: this });
    }
}


class FakeMutationObserver {
    constructor(callback) {
        this.callback = callback;
    }

    observe() {}
    disconnect() {}
}


function runAppearanceWithSidebar() {
    const body = new FakeElement('body');
    const head = new FakeElement('head');
    const sidebarBottom = new FakeElement('', ['sidebar-bottom']);
    const help = new FakeElement('mlxSidebarHelpButton', ['sidebar-action']);
    const settings = new FakeElement('sidebarSettingsButton', ['sidebar-action']);
    const studioLauncher = new FakeElement('', ['mlx-shorts-studio-launcher']);
    const historyLauncher = new FakeElement('', ['mlx-shorts-history-launcher']);
    const runtime = new FakeElement('', ['sidebar-runtime']);
    let historyClicks = 0;
    historyLauncher.addEventListener('click', () => { historyClicks += 1; });

    sidebarBottom.appendChild(help);
    sidebarBottom.appendChild(settings);
    sidebarBottom.appendChild(runtime);
    body.appendChild(sidebarBottom);
    body.appendChild(studioLauncher);
    body.appendChild(historyLauncher);

    const byId = new Map([
        ['mlxSidebarHelpButton', help],
        ['sidebarSettingsButton', settings],
    ]);

    globalThis.localStorage = {
        getItem() { return null; },
        setItem() {},
    };
    globalThis.MutationObserver = FakeMutationObserver;
    globalThis.document = {
        readyState: 'complete',
        body,
        head,
        documentElement: new FakeElement('html'),
        getElementById(id) {
            if (id === 'mlxShortsSidebarStyles') {
                return head.children.find(child => child.id === id) || null;
            }
            return byId.get(id) || null;
        },
        querySelector(selector) {
            if (selector === '.sidebar-bottom') return sidebarBottom;
            if (selector === '.mlx-shorts-history-launcher') return historyLauncher;
            if (selector === '.appearance-bubble-preview') return null;
            return null;
        },
        createElement() {
            return new FakeElement();
        },
        addEventListener() {},
    };

    const source = fs.readFileSync(
        new URL('../frontend/assets/chat/appearance.js', import.meta.url),
        'utf8'
    );
    vm.runInThisContext(source, {
        filename: 'frontend/assets/chat/appearance.js'
    });

    return {
        body,
        head,
        sidebarBottom,
        help,
        studioLauncher,
        historyLauncher,
        settings,
        runtime,
        clickHistoryLauncher() {
            historyLauncher.click();
            return historyClicks;
        },
    };
}


test('Shorts history launcher moves between Help and Settings without losing its handler', () => {
    const {
        sidebarBottom,
        help,
        historyLauncher,
        settings,
        runtime,
        clickHistoryLauncher,
    } = runAppearanceWithSidebar();

    assert.deepEqual(
        sidebarBottom.children,
        [help, historyLauncher, settings, runtime]
    );
    assert.equal(historyLauncher.classList.contains('sidebar-action'), true);
    assert.equal(clickHistoryLauncher(), 1);
});


test('legacy Shorts Studio floating launcher is forcibly hidden', () => {
    const { head, studioLauncher, body } = runAppearanceWithSidebar();
    const style = head.children.find(child => child.id === 'mlxShortsSidebarStyles');

    assert.ok(style);
    assert.match(style.textContent, /\.mlx-shorts-studio-launcher\s*\{[^}]*display:\s*none\s*!important/s);
    assert.equal(studioLauncher.parentElement, body);
});


test('Help, Shorts and Settings use matching decorative SVG icons and label columns', () => {
    const help = fs.readFileSync('frontend/assets/chat/help.js', 'utf8');
    const history = fs.readFileSync('frontend/assets/chat/shorts-history.js', 'utf8');
    const html = fs.readFileSync('frontend/chat.html', 'utf8');
    const settings = html.match(/<button id="sidebarSettingsButton"[^>]*>([\s\S]*?)<\/button>/)[1];
    const icons = [
        help.match(/button\.innerHTML = '(<svg[^']+)'/)[1],
        history.match(/launcher\.innerHTML = '(<svg[^']+)'/)[1],
        settings,
    ];
    for (const icon of icons) {
        assert.match(icon, /width="18" height="18"/);
        assert.match(icon, /viewBox="0 0 24 24"/);
        assert.match(icon, /fill="none" stroke="currentColor" stroke-width="1\.8"/);
        assert.match(icon, /aria-hidden="true"/);
    }
    assert.match(settings, /class="sidebar-action-label" data-i18n="ui.settings"/);
    assert.match(help, /sideButton\.querySelector\('\.sidebar-action-label'\)\.textContent/);
    assert.match(history, /ui\.launcherLabel\.textContent = count/);
    assert.doesNotMatch(history, /ui\.launcher\.textContent\s*=/);
});
