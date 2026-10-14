import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const source = fs.readFileSync('frontend/assets/chat/image-compare.js', 'utf8');

class Element {
    constructor(tag) {
        this.tagName = tag.toUpperCase();
        this.children = [];
        this.style = {};
        this.events = {};
        this.isConnected = true;
        this.attributes = {};
        this.open = false;
    }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); }
    addEventListener(name, fn) { this.events[name] = fn; }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { if (name === 'src') delete this.src; }
    showModal() { this.open = true; }
    close() { this.open = false; this.events.close?.(); }
    focus() { this.focused = true; }
    querySelector(selector) {
        if (selector === '.image-compare-stage') return this.children[1];
        if (selector === '#imageCompareTitle') return this.children[0].children[0];
        if (selector === '.image-compare-controls span') return this.children[2].children[0];
        return null;
    }
}

function environment() {
    const listeners = {};
    const body = new Element('body');
    body.classList = {add(name) { body.lastClass = name; }, remove(name) { body.lastRemoved = name; }};
    const document = {body, activeElement: null, createElement: name => new Element(name),
        addEventListener(name, fn) { (listeners[name] ||= []).push(fn); }};
    const window = {MLXI18n: {t(_key, fallback) { return fallback; }}};
    const context = {document, window};
    vm.runInNewContext(source, context);
    vm.runInNewContext(source, context);
    return {document, window, listeners, body};
}

const before = '1791991459-74bc183bce56';
const after = '1791991547-5cf5b691955b';

test('Image compare never accepts raw paths, arbitrary URLs or invalid IDs', () => {
    const {window, body} = environment();
    assert.equal(window.MLXImageCompare.open({beforeId: '/tmp/private.png', afterId: after}), false);
    assert.equal(window.MLXImageCompare.open({beforeId: before, afterId: 'https://example.com/tracker'}), false);
    assert.equal(window.MLXImageCompare.open({beforeId: before, afterId: before}), false);
    assert.equal(body.children.length, 0);
});

test('Two images align in one modal; range is accessible and close clears sources', () => {
    const {window, body, listeners} = environment();
    const trigger = new Element('button');
    assert.equal(window.MLXImageCompare.open({beforeId: before, afterId: after, width: 672, height: 1024}, trigger), true);
    assert.equal(body.children.length, 1);
    const dialog = body.children[0];
    assert.equal(dialog.open, true);
    const stage = dialog.children[1];
    assert.equal(Number(stage.style.aspectRatio), 672 / 1024);
    const [edited, original] = stage.children;
    assert.equal(edited.src, '/api/mlx/images/' + after);
    assert.equal(original.src, '/api/mlx/images/' + before);
    assert.equal(original.style.clipPath, 'inset(0 50% 0 0)');
    const range = dialog.children[2].children[1];
    assert.equal(range.type, 'range');
    assert.equal(range.attributes['aria-label'], 'Original image visibility');
    assert.equal(range.focused, true);
    range.value = '75';
    range.events.input();
    assert.equal(original.style.clipPath, 'inset(0 25% 0 0)');
    assert.equal(listeners['mlx-language-changed'].length, 1);
    listeners['mlx-language-changed'][0]();
    dialog.close();
    assert.equal(original.src, undefined);
    assert.equal(edited.src, undefined);
    assert.equal(trigger.focused, true);
    assert.equal(body.lastRemoved, 'image-preview-open');
});
