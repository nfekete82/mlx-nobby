import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';


const source = fs.readFileSync(
    new URL('../frontend/assets/chat/i18n.js', import.meta.url),
    'utf8',
);
const catalogs = {
    en: JSON.parse(fs.readFileSync(new URL('../frontend/i18n/en.json', import.meta.url))),
    de: JSON.parse(fs.readFileSync(new URL('../frontend/i18n/de.json', import.meta.url))),
};

function element(dataset = {}) {
    return {
        dataset,
        textContent: '',
        attributes: {},
        setAttribute(name, value) {
            this.attributes[name] = value;
        },
    };
}

const textElement = element({ i18n: 'notes.save_note' });
const placeholderElement = element({ i18nPlaceholder: 'ui.note_content' });
const titleElement = element({ i18nTitle: 'ui.show_chats' });
const ariaElement = element({ i18nAriaLabel: 'ui.local_service_status' });
const selector = {
    value: '',
    addEventListener() {},
};
const listeners = new Map();
const stored = new Map();

const document = {
    documentElement: { lang: '' },
    addEventListener(name, callback) {
        listeners.set(name, callback);
    },
    dispatchEvent(event) {
        listeners.get(event.type)?.(event);
    },
    getElementById(id) {
        return id === 'interfaceLanguage' ? selector : null;
    },
    querySelectorAll(query) {
        return {
            '[data-i18n]': [textElement],
            '[data-i18n-placeholder]': [placeholderElement],
            '[data-i18n-title]': [titleElement],
            '[data-i18n-aria-label]': [ariaElement],
        }[query] || [];
    },
};
const localStorage = {
    getItem(key) {
        return stored.get(key) ?? null;
    },
    setItem(key, value) {
        stored.set(key, value);
    },
};
const sandbox = {
    console,
    document,
    localStorage,
    navigator: { language: 'de-DE' },
    CustomEvent: class {
        constructor(type, options = {}) {
            this.type = type;
            this.detail = options.detail;
        }
    },
    fetch: async url => ({
        ok: true,
        async json() {
            return structuredClone(catalogs[url.includes('/de.json') ? 'de' : 'en']);
        },
    }),
    window: {},
};
sandbox.window.window = sandbox.window;

vm.runInNewContext(source, sandbox, { filename: 'i18n.js' });

await sandbox.window.MLXI18n.init();
assert.equal(sandbox.window.MLXI18n.getLanguage(), 'en');
assert.equal(document.documentElement.lang, 'en');
assert.equal(textElement.textContent, 'Save note');
assert.equal(placeholderElement.attributes.placeholder, 'Note text…');
assert.equal(titleElement.attributes.title, 'Show chats');
assert.equal(ariaElement.attributes['aria-label'], 'Local service status');
assert.equal(sandbox.window.MLXI18n.t('profile.title'), 'Personal profile');

await sandbox.window.MLXI18n.setLanguage('de');
assert.equal(stored.get('mlx-nobby-language'), 'de');
assert.equal(sandbox.window.MLXI18n.getLanguage(), 'de');
assert.equal(textElement.textContent, 'Notiz speichern');
assert.equal(placeholderElement.attributes.placeholder, 'Notiztext…');

console.log('i18n runtime: English default, attributes, flat keys, and persistence passed.');
