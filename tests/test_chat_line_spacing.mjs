import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const js = readFileSync(new URL('../frontend/assets/chat/appearance.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../frontend/assets/chat.css', import.meta.url), 'utf8');
const html = readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');
const de = JSON.parse(readFileSync(new URL('../frontend/i18n/de.json', import.meta.url), 'utf8'));
const en = JSON.parse(readFileSync(new URL('../frontend/i18n/en.json', import.meta.url), 'utf8'));

const STORAGE_KEY = 'mlx-web-chat-appearance-v1';

function mountAppearance(seed = null, lang = 'de') {
    const stored = new Map();
    if (seed !== null) stored.set(STORAGE_KEY, JSON.stringify(seed));
    const cssVars = new Map();
    const events = new Map();
    const elements = new Map();
    for (const id of [
        'chatFontSize', 'chatFontSizeValue', 'chatLineHeight', 'chatLineHeightValue',
        'userBubbleColor', 'userBubbleHex', 'resetAppearance'
    ]) {
        elements.set(id, {
            value: '',
            textContent: '',
            addEventListener(type, fn) { events.set(id + ':' + type, fn); }
        });
    }
    const preview = { style: {} };
    const document = {
        readyState: 'complete',
        documentElement: {
            lang,
            style: { setProperty(k, v) { cssVars.set(k, v); } }
        },
        getElementById(id) { return elements.get(id) || null; },
        querySelector(selector) {
            return selector === '.appearance-bubble-preview' ? preview : null;
        },
        createElement() { return { id: '', textContent: '' }; },
        head: { appendChild(element) { elements.set(element.id, element); } },
    };
    vm.runInNewContext(js, {
        document,
        localStorage: {
            getItem(key) { return stored.get(key) || null; },
            setItem(key, val) { stored.set(key, val); }
        }
    }, { filename: 'appearance.js' });
    return {
        stored,
        cssVars,
        preview,
        get: id => elements.get(id),
        fire(id, type, value) {
            const element = elements.get(id);
            if (value !== undefined) element.value = value;
            const callback = events.get(id + ':' + type);
            assert.equal(typeof callback, 'function', id + ':' + type + ' listener missing');
            callback({ target: element });
        }
    };
}

test('existing users retain 1.68 line height and their saved colors and font sizes', () => {
    const app = mountAppearance({ font_size: 18, user_bubble_color: '#AABBCC' });
    assert.equal(app.cssVars.get('--chat-font-size'), '18px');
    assert.equal(app.cssVars.get('--chat-line-height'), '1.68');
    assert.equal(app.cssVars.get('--user-bubble-color'), '#aabbcc');
    assert.equal(app.get('chatLineHeight').value, '1.68');
    assert.match(app.get('chatLineHeightValue').textContent, /1,68/);
});

test('slider applies immediately, saves changes and restores after remount', () => {
    const app = mountAppearance();
    app.fire('chatLineHeight', 'input', '1.35');
    assert.equal(app.cssVars.get('--chat-line-height'), '1.35');
    assert.equal(JSON.parse(app.stored.get(STORAGE_KEY)).line_height, 1.35);
    const restored = mountAppearance(JSON.parse(app.stored.get(STORAGE_KEY)), 'en');
    assert.equal(restored.cssVars.get('--chat-line-height'), '1.35');
    assert.match(restored.get('chatLineHeightValue').textContent, /1\.35/);
});

test('malformed out-of-range values are clamped or defaulted', () => {
    for (const [value, expected] of [
        [1.0, '1.2'], [2.5, '2'], ['oops', '1.68'],
        [null, '1.68'], ['', '1.68']
    ]) {
        const app = mountAppearance({ line_height: value });
        assert.equal(app.cssVars.get('--chat-line-height'), expected);
    }
});

test('reset restores line height, font size and bubble color together', () => {
    const app = mountAppearance({ line_height: 1.25, font_size: 19, user_bubble_color: '#ff0000' });
    app.fire('resetAppearance', 'click');
    assert.equal(app.cssVars.get('--chat-line-height'), '1.68');
    assert.equal(app.cssVars.get('--chat-font-size'), '15px');
    assert.equal(app.cssVars.get('--user-bubble-color'), '#2f6fea');
    assert.equal(JSON.parse(app.stored.get(STORAGE_KEY)).line_height, 1.68);
});

test('UI and CSS expose a local, accessible live line spacing setting', () => {
    assert.match(html, /<label for="chatLineHeight">/);
    assert.match(html, /id="chatLineHeight"\s+type="range"/);
    assert.match(html, /min="1\.2"\s+max="2"\s+step="0\.01"/);
    assert.match(html, /id="chatLineHeightHint"/);
    assert.match(css, /--chat-line-height:\s*1\.68;/);
    assert.match(css, /\.message-content\s*\{[^}]*line-height:\s*var\(--chat-line-height\)/s);
    assert.match(css, /\.appearance-bubble-preview\s*\{[^}]*line-height:\s*var\(--chat-line-height\)/s);
    assert.equal(de.appearance.line_spacing, 'Zeilenabstand');
    assert.equal(en.appearance.line_spacing, 'Line spacing');
});
