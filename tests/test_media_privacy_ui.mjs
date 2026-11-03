import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const script = readFileSync(new URL('../frontend/assets/chat/media-privacy.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../frontend/assets/chat/media-privacy.css', import.meta.url), 'utf8');
const html = readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');

function createHarness(initial = '0') {
    const events = new Map();
    const values = new Map([['mlx.mediaPrivacy.enabled.v1', initial]]);
    const htmlClasses = new Set();
    const nodes = {};
    function classes() {
        const all = new Set();
        return {
            contains: key => all.has(key),
            add: key => all.add(key),
            remove: key => all.delete(key),
            toggle(key, state) {
                if (state === undefined ? !all.has(key) : !!state) all.add(key);
                else all.delete(key);
            }
        };
    }
    const setting = {checked: false, addEventListener(k, cb) {this[k] = cb;}};
    const quick = {
        classList: classes(),
        attributes: {},
        addEventListener(k, cb) {this[k] = cb;},
        setAttribute(k, v) {this.attributes[k] = v;}
    };
    const document = {
        documentElement: {
            classList: {
                toggle(name, value) {
                    if (value) htmlClasses.add(name); else htmlClasses.delete(name);
                }
            }
        },
        getElementById(id) {
            return {'mediaPrivacyToggle': setting, 'mediaPrivacyQuickToggle': quick}[id] || null;
        },
        querySelectorAll() {return [];},
        addEventListener(type, callback) {
            const current = events.get(type) || [];
            events.set(type, [...current, callback]);
        }
    };
    const storage = {
        getItem: name => values.get(name) || null,
        setItem: (name, value) => values.set(name, value)
    };
    const window = {MLXI18n: {t: (_key, fallback) => fallback}};
    vm.runInNewContext(script, {document, window, localStorage: storage});
    const fire = (type, value) => {
        for (const callback of events.get(type) || []) callback(value);
    };
    return {window, fire, values, htmlClasses, setting, quick, classes};
}

test('saved preference applies before any media or document body renders', () => {
    const h = createHarness('1');
    assert.equal(h.htmlClasses.has('mlx-media-privacy-on'), true);
    assert.equal(h.window.MLXMediaPrivacy.enabled(), true);
    h.fire('DOMContentLoaded');
    assert.equal(h.setting.checked, true);
    assert.equal(h.quick.attributes['aria-pressed'], 'true');
});

test('settings and quick action stay synchronized and persist locally', () => {
    const h = createHarness('0');
    h.fire('DOMContentLoaded');
    assert.equal(h.quick.attributes['aria-pressed'], 'false');
    h.setting.change({target: {checked: true}});
    assert.equal(h.values.get('mlx.mediaPrivacy.enabled.v1'), '1');
    assert.equal(h.quick.attributes['aria-pressed'], 'true');
    h.quick.click();
    assert.equal(h.setting.checked, false);
    assert.equal(h.values.get('mlx.mediaPrivacy.enabled.v1'), '0');
});

test('touch needs one reveal tap before media click actions', () => {
    const h = createHarness('1');
    h.fire('DOMContentLoaded');
    const media = {classList: h.classes(), closest: () => media, contains: () => false};
    let stopped = 0;
    const click = {
        target: media,
        preventDefault() {stopped += 1;},
        stopImmediatePropagation() {stopped += 1;}
    };
    h.fire('pointerdown', {pointerType: 'touch', target: media});
    h.fire('click', click);
    assert.equal(media.classList.contains('mlx-media-tap-revealed'), true);
    assert.equal(stopped, 2);
    h.fire('pointerdown', {pointerType: 'touch', target: media});
    h.fire('click', click);
    assert.equal(stopped, 2);
});

test('front-end covers media library, chat images/videos and lightbox', () => {
    for (const selector of [
        '.message-attachment-preview',
        '.image-artifact-preview',
        '.video-artifact-player',
        '.image-variant-preview',
        '.nobby-library-media > img',
        '.nobby-library-preview-body > video',
        '.image-preview-dialog img',
        '.image-compare-stage img'
    ]) {
        assert.ok(script.includes(selector), 'missing JS media selector: ' + selector);
        assert.ok(css.includes(selector), 'missing CSS media selector: ' + selector);
    }
    assert.ok(html.indexOf('/assets/chat/media-privacy.js') < html.indexOf('<body'));
    assert.ok(html.includes('id="mediaPrivacyToggle"'));
    assert.ok(html.includes('id="mediaPrivacyQuickToggle"'));
    assert.ok(css.includes('blur(30px)'));
    assert.ok(css.includes(':hover'));
});
