import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const original = fs.readFileSync('frontend/assets/chat/media-library.js', 'utf8');
const marker = /\}\)\(\);\s*$/;
assert.match(original, marker);
const code = original.replace(marker, 'globalThis.__showPreview = showPreview;\nglobalThis.__card = card;\n})();');

function createFixture(onFetch, onEdit = () => {}) {
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
      this.classList = {add() {}, remove() {}, toggle() {}};
      this.hidden = false;
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); return child; }
    replaceChildren(...children) { this.children = [...children]; }
    addEventListener(name, fn) { this.events[name] = fn; }
    focus() { activeElement = this; }
    pause() {}
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
  const scope = {document, window: {MLXVideoEdit: {open: onEdit}}, fetch: onFetch, console, setTimeout, clearTimeout};
  vm.runInNewContext(code, scope, {filename: 'media-library.js'});
  const preview = body.children.find(child => child.className === 'nobby-library-preview');
  const previewBody = preview.children[1].children[2];
  const show = asset => scope.__showPreview(asset);
  const actions = () => previewBody.children.find(x => x.className === 'nobby-library-preview-actions');
  const details = () => previewBody.children.find(x => x.className === 'nobby-library-detail-panel');
  return {show, actions, details, previewBody, preview, card: asset => scope.__card(asset)};
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

test('video preview has two LTX edit actions and one accessible details action', async () => {
  const f = createFixture(async () => ({ok: true, json: async () => ({...metadata, kind: 'video'})}));
  f.show({...asset, kind: 'video'});
  const actions = f.actions().children;
  assert.equal(actions.length, 3);
  assert.equal(actions[0].children[1].textContent, 'Video verlängern');
  assert.equal(actions[1].children[1].textContent, 'Bereich neu erstellen');
  assert.equal(actions[2].getAttribute('aria-expanded'), 'false');
  assert.equal(actions.filter(button => button.getAttribute('aria-controls') ===
    'nobby-library-preview-details').length, 1);
  await actions[2].click();
  assert.equal(f.details().hidden, false);
});

test('video preview Extend and Retake buttons open the real editor for the chosen source', async () => {
  const opened = [];
  const f = createFixture(async () => ({ok: true, json: async () => ({...metadata, kind: 'video'})}),
                          (asset, mode) => {opened.push({asset, mode});});
  const video = {...asset, id: 'a'.repeat(24), kind: 'video'};
  f.show(video);
  await f.actions().children[0].click();
  assert.equal(opened.length, 1);
  assert.equal(opened[0].mode, 'extend');
  assert.equal(opened[0].asset.id, video.id);
  f.show(video);
  await f.actions().children[1].click();
  assert.equal(opened.length, 2);
  assert.equal(opened[1].mode, 'retake');
});

test('video card Actions menu contains Extend and Retake with working editor links', async () => {
  const opened = [];
  const f = createFixture(async () => ({ok: true, json: async () => ({...metadata, kind: 'video'})}),
                          (asset, mode) => {opened.push({asset, mode});});
  const video = {...asset, id: 'b'.repeat(24), kind: 'video'};
  const rendered = f.card(video);
  const all = node => [node, ...node.children.flatMap(all)];
  const menu = all(rendered).find(node => node.className?.includes('nobby-library-card-action-menu'));
  assert.ok(menu, 'video menu exists');
  assert.equal(menu.children[0].children[1].textContent, 'Video verlängern');
  assert.equal(menu.children[1].children[1].textContent, 'Bereich neu erstellen');
  await menu.children[0].click();
  await menu.children[1].click();
  assert.deepEqual(opened.map(item => item.mode), ['extend', 'retake']);
  assert.equal(opened[0].asset.id, video.id);
});
