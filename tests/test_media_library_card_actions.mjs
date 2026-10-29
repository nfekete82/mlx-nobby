import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync('frontend/assets/chat/media-library.js', 'utf8');
assert.match(source, /\}\)\(\);\s*$/);
const script = source.replace(/\}\)\(\);\s*$/, 'globalThis.__makeCard = card;\n})();');

function setup() {
  const listeners = {};
  class Element {
    constructor(tag = 'div') {
      this.tag = tag;
      this.children = [];
      this.events = {};
      this.attributes = {};
      this.dataset = {};
      this.hidden = false;
      this.isConnected = true;
      this.className = '';
      this.classList = {
        add: name => { this.className += ' ' + name; },
        remove: name => { this.className = this.className.replace(name, ''); },
        toggle() {}
      };
    }
    setAttribute(name, val) { this.attributes[name] = String(val); }
    getAttribute(name) { return this.attributes[name]; }
    append(...children) {
      for (const child of children) { child.parent = this; this.children.push(child); }
    }
    appendChild(child) { this.append(child); return child; }
    replaceChildren(...children) { this.children = []; this.append(...children); }
    addEventListener(type, fn) { (this.events[type] ||= []).push(fn); }
    contains(target) {
      for (let el = target; el; el = el.parent) if (el === this) return true;
      return false;
    }
    focus() { this.focused = true; }
    querySelectorAll() { return []; }
    querySelector(selector) {
      return this.children.find(el => el.tag === selector) || null;
    }
    fire(type, event = {}) {
      const obj = {
        target: this,
        key: event.key,
        prevented: false,
        stopped: false,
        preventDefault() { this.prevented = true; },
        stopPropagation() { this.stopped = true; }
      };
      for (const fn of this.events[type] || []) fn(obj);
      return obj;
    }
  }
  const ids = new Map([
    ['nobbyLibrary', new Element()],
    ['nobbyLibraryGrid', new Element()],
    ['sidebarLibraryButton', new Element()],
    ['nobbyLibraryClose', new Element()]
  ]);
  const body = new Element('body');
  const document = {
    body, documentElement: {lang: 'de'}, activeElement: null,
    createElement: tag => new Element(tag),
    createElementNS: (_, tag) => new Element(tag),
    createDocumentFragment: () => new Element('fragment'),
    getElementById: id => ids.get(id) || null,
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }
  };
  const context = {document, window: {}, fetch: async () => ({ok: true}),
    console, setTimeout, clearTimeout};
  vm.runInNewContext(script, context, {filename: 'media-library.js'});
  const make = (kind = 'image', id = 'photo-1') => context.__makeCard({
    kind, id, url: '/api/library/assets/' + kind + '/' + id,
    created_at: 1792560000, persistent: false
  });
  const locate = (card, name) => card.children[1].children.find(child =>
    child.className.includes(name));
  const actions = card => locate(card, 'nobby-library-card-actions');
  const row = card => actions(card).children[0];
  const menu = card => actions(card).children[1];
  const toggle = card => row(card).children[1];
  return {make, actions, row, menu, toggle, listeners, Element};
}

test('image cards start compact with Download, Actions and five icon-labelled items', () => {
  const f = setup(), card = f.make();
  const row = f.row(card), menu = f.menu(card);
  assert.equal(row.children.length, 2);
  assert.equal(row.children[0].tag, 'a');
  assert.equal(row.children[0].href.endsWith('?download=1'), true);
  assert.equal(row.children[0].children[0].tag, 'svg');
  assert.equal(row.children[1].getAttribute('aria-expanded'), 'false');
  assert.equal(menu.hidden, true);
  assert.equal(menu.children.length, 5);
  for (const button of menu.children) {
    assert.equal(button.tag, 'button');
    assert.equal(button.children[0].tag, 'svg');
    assert.equal(button.children[0].attributes['aria-hidden'], 'true');
    assert.ok(button.children[1].textContent?.length);
  }
  assert.equal(menu.children[3].children[1].textContent, 'Details');
  assert.equal(menu.children[4].children[1].textContent, 'Löschen');
});

test('a click toggles a card menu and opening another automatically closes it', () => {
  const f = setup(), first = f.make('image', 'first'), second = f.make('image', 'second');
  f.toggle(first).fire('click');
  assert.equal(f.menu(first).hidden, false);
  assert.equal(f.toggle(first).getAttribute('aria-expanded'), 'true');
  f.toggle(first).fire('click');
  assert.equal(f.menu(first).hidden, true);
  f.toggle(first).fire('click');
  f.toggle(second).fire('click');
  assert.equal(f.menu(first).hidden, true);
  assert.equal(f.toggle(first).getAttribute('aria-expanded'), 'false');
  assert.equal(f.menu(second).hidden, false);
  f.menu(second).fire('click');
  assert.equal(f.menu(second).hidden, true, 'choosing a menu item closes the disclosure');
});

test('Escape restores focus; outside clicks dismiss; video card exposes editor actions', () => {
  const f = setup(), image = f.make(), video = f.make('video');
  f.toggle(image).fire('click');
  const key = f.actions(image).fire('keydown', {key: 'Escape'});
  assert.equal(key.prevented, true);
  assert.equal(key.stopped, true);
  assert.equal(f.toggle(image).focused, true);
  assert.equal(f.menu(image).hidden, true);
  f.toggle(image).fire('click');
  for (const onClick of f.listeners.click || []) onClick({target: new f.Element('outside')});
  assert.equal(f.menu(image).hidden, true);
  assert.equal(f.menu(video).children.length, 4);
  assert.equal(f.menu(video).children[0].children[1].textContent, 'Video verlängern');
  assert.equal(f.menu(video).children[1].children[1].textContent, 'Bereich neu erstellen');
  assert.equal(f.menu(video).children[2].children[1].textContent, 'Details');
  assert.equal(f.menu(video).children[3].children[1].textContent, 'Löschen');
});
