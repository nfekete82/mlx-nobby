import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/assets/chat/image-preview.js', 'utf8');
class Element {
    constructor(tag = 'img') {
        this.tag = tag; this.children = []; this.events = {}; this.isConnected = true;
        this.classes = new Set();
        this.classList = {add: value => this.classes.add(value), remove: value => this.classes.delete(value)};
    }
    setAttribute(name, value) { this[name] = value; }
    removeAttribute(name) { delete this[name]; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); }
    addEventListener(type, callback) { this.events[type] = callback; }
    showModal() { this.open = true; }
    close() { this.open = false; this.events.close(); }
    focus() { this.focused = true; }
    matches(selector) { return selector.split(',').some(value => value.trim() === '.' + this.className); }
    closest(selector) { return this.matches(selector) ? this : this.parent?.closest(selector); }
    querySelector() { return this.children[0]; }
}
const listeners = {};
const body = new Element('body');
const document = {body, createElement: tag => new Element(tag),
    addEventListener(type, callback) { (listeners[type] ||= []).push(callback); }};
let language = 'en';
const window = {MLXI18n: {t(_key, fallback) { return language === 'de' ? 'Bildvorschau' : fallback; }}};
const context = {document, window};
vm.runInNewContext(source, context);
vm.runInNewContext(source, context);
assert.equal(listeners.click.length, 1, 'repeated evaluation keeps one dialog handler');
const fire = (type, target, extra = {}) => {
    const event = {target, preventDefault() { this.prevented = true; }, ...extra};
    listeners[type].forEach(callback => callback(event)); return event;
};
for (const kind of ['message-attachment-preview', 'image-artifact-preview', 'image-variant-preview']) {
    const image = new Element(); image.className = kind; image.src = '/fixture/' + kind + '.png'; image.alt = kind;
    if (kind === 'image-variant-preview') {
        image.parent = new Element('a'); image.parent.className = 'image-variant-preview-link'; image.parent.append(image);
    }
    assert.equal(fire('click', image).prevented, true);
    assert.equal(body.children.length, 1);
    const dialog = body.children[0];
    assert.equal(dialog.open, true);
    assert.equal(dialog.children[1].src, image.src);
    assert.equal(dialog.children[1].alt, kind);
    assert.equal(body.classes.has('image-preview-open'), true);
    dialog.children[0].children[1].events.click();
    assert.equal(dialog.open, false);
    assert.equal(body.classes.has('image-preview-open'), false);
    assert.equal((image.parent || image).focused, true);
    assert.equal(dialog.children[1].src, undefined);
    fire('click', image.parent || image);
    dialog.events.click({target: dialog});
    assert.equal(dialog.open, false, 'backdrop closes the same dialog');
    if (kind !== 'image-variant-preview') {
        assert.equal(fire('keydown', image, {key: 'Enter'}).prevented, true);
        assert.equal(dialog.open, true);
        dialog.close();
    }
    assert.equal(fire('click', image, {ctrlKey: true}).prevented, undefined);
    assert.equal(dialog.open, false, 'modified gallery links retain native behavior');
}
language = 'de'; fire('mlx-language-changed', body);
assert.equal(body.children[0].children[0].children[0].textContent, 'Bildvorschau');
console.log('Chat uploads, generated images and gallery share one accessible image dialog.');
