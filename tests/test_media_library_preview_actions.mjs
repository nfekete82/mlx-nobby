import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const original = fs.readFileSync('frontend/assets/chat/media-library.js', 'utf8');
const marker = /\}\)\(\);\s*$/;
assert.match(original, marker);
const code = original.replace(marker, 'globalThis.__showPreview = showPreview;\n})();');

function createFixture(onFetch) {
  const nodes = new Map();
  let activeElement = null;
  class Element {
    constructor(tag = 'div') {
      this.tag = tag;
      this.children = [];
      this.attributes = {};
      this.events = {};
      this.className = '';
      this.isConnected = true;
      this.hidden = false;
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); return child; }
    replaceChildren(...children) { this.children = [...children]; }
    addEventListener(name, fn) { this.events[name] = fn; }
    focus() { activeElement = this; }
    querySelector(selector) {
      return this.children.find(child => child.tag === selector) || null;
    }
    querySelectorAll() { return []; }
    async click() { return this.events.click?.(); }
  }
  const ids = ['nobbyLibrary', 'nobbyLibraryGrid', 'sidebarLibraryButton', 'nobbyLibraryClose'];
  for (const id of ids) nodes.set(id, new Element('div'));
  const body = new Element('body');
  const document = {
    body,
    get activeElement() { return activeElement; },
    documentElement: {lang: 'de'},
    getElementById: id => nodes.get(id) || null,
    createElement: tag => new Element(tag),
    createElementNS: (_, tag) => new Element(tag),
    addEventListener() {}
  };
  const scope = {document, window: {}, fetch: onFetch, console, setTimeout, clearTimeout};
  vm.runInNewContext(code, scope, {filename: 'media-library.js'});
  const preview = body.children.find(child => child.className === 'nobby-library-preview');
  const previewBody = preview.children[1].children[2];
  const show = asset => scope.__showPreview(asset);
  const actions = () => previewBody.children.find(x => x.className === 'nobby-library-preview-actions');
  const details = () => previewBody.children.find(x => x.className === 'nobby-library-detail-panel');
  return {show, actions, details, previewBody, preview};
}

const asset = {kind: 'image', id: 'fixture123', url: '/image.png', created_at: 1792560000};
const metadata = {kind: 'image', id: 'fixture123', size_bytes: 1024, width: 720, height: 1024, created_at: 1792560000};

test('gallery actions are grouped, each with its own decorative SVG and visible label', () => {
  const f = createFixture(async () => ({ok: true, json: async () => metadata}));
  f.show(asset);
  const row = f.actions();
  assert.ok(row);
  assert.equal(row.children.length, 4);
  for (const control of row.children) {
    assert.equal(control.tag, 'button');
    assert.equal(control.children[0].tag, 'svg');
    assert.equal(control.children[0].getAttribute('aria-hidden'), 'true');
    assert.equal(control.children[1].tag, 'span');
    assert.ok(control.children[1].textContent?.length);
  }
  assert.equal(row.children[3].getAttribute('aria-expanded'), 'false');
  assert.equal(f.details().hidden, true);
});

test('details toggles open and closed, reuses data and updates aria-expanded', async () => {
  let requests = 0;
  const f = createFixture(async () => { ++requests; return {ok: true, json: async () => metadata}; });
  f.show(asset);
  const button = f.actions().children[3];
  await button.click();
  assert.equal(f.details().hidden, false);
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  assert.equal(button.children[1].textContent, 'Details ausblenden');
  assert.equal(requests, 1);
  assert.ok(f.details().children.length > 2);

  await button.click();
  assert.equal(f.details().hidden, true);
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  assert.equal(button.children[1].textContent, 'Details anzeigen');

  await button.click();
  assert.equal(f.details().hidden, false);
  assert.equal(requests, 1, 'no repeat fetch after already loading valid details');
});

test('closing during pending details request ignores stale network results', async () => {
  let finish;
  let requests = 0;
  const f = createFixture(() => {
    ++requests;
    return new Promise(resolve => { finish = resolve; });
  });
  f.show(asset);
  const button = f.actions().children[3];
  const pending = button.click();
  assert.equal(f.details().hidden, false);
  await button.click();
  assert.equal(f.details().hidden, true);
  finish({ok: true, json: async () => metadata});
  await pending;
  assert.equal(f.details().hidden, true);
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  assert.equal(requests, 1);
});

test('video preview retains one accessible details action', async () => {
  const f = createFixture(async () => ({ok: true, json: async () => ({...metadata, kind: 'video'})}));
  f.show({...asset, kind: 'video'});
  assert.equal(f.actions().children.length, 1);
  await f.actions().children[0].click();
  assert.equal(f.details().hidden, false);
});
