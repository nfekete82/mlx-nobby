import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync('frontend/assets/chat/video-edit.js', 'utf8');
const id = 'a'.repeat(24);
const active = (extra = {}) => ({id, source_kind: 'video', source_id: 'b'.repeat(24),
  status: 'generating', phase: 'generating', progress: null, started_at: Date.now()/1000 - 12, ...extra});
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };

function browser({job = null, saved = null, brokenStorage = false} = {}) {
  const nodes = [], requests = [], timers = new Map(), events = new Map();
  const storage = new Map(saved ? [['mlx-video-edit-active-v1', saved]] : []);
  let serial = 0, failPoll = false, failCancel = false, failDiscovery = false, creates = 0;
  let current = job;
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {}; this.hidden = false; this.style = {}; nodes.push(this); }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); }
    setAttribute(key, value) { this.attrs[key] = value; }
    removeAttribute(key) { delete this.attrs[key]; if (key === 'value') delete this.value; }
    addEventListener(key, fn) { this.listeners[key] = fn; }
    focus() {}
    getClientRects() { return [1]; }
    querySelectorAll() { return nodes; }
  }
  const window = {addEventListener: (type, callback) => events.set(type, callback), dispatchEvent() {}};
  const context = {
    window, navigator: {language: 'de'}, URLSearchParams, Event, AbortController, console,
    document: {documentElement: {lang: 'de'}, createElement: tag => new Element(tag),
      head: new Element('head'), body: new Element('body'), addEventListener() {}, activeElement: null},
    localStorage: {
      getItem: key => { if (brokenStorage) throw Error('blocked'); return storage.get(key) ?? null; },
      setItem: (key, value) => { if (brokenStorage) throw Error('blocked'); storage.set(key, value); },
      removeItem: key => storage.delete(key),
    },
    setTimeout: callback => { timers.set(++serial, callback); return serial; },
    clearTimeout: key => timers.delete(key), setInterval: () => 1, clearInterval() {},
    async fetch(url, options = {}) {
      requests.push({url, options});
      let payload, code = 200;
      if (url === '/api/mlx/video/edit/jobs' && options.method === 'POST') {
        creates++;
        current = active({status: 'queued', phase: 'queued'});
        payload = current;
      } else if (url === '/api/mlx/video/edit/jobs') {
        if (failDiscovery) throw Error('offline');
        payload = {jobs: current && !['completed', 'cancelled', 'failed'].includes(current.status) ? [current] : []};
      } else if (url.includes('/cancel')) {
        if (failCancel) throw Error('network');
        current = {...current, status: 'cancelling', cancel_requested: true};
        payload = current;
      } else if (url.includes('/status?')) {
        payload = {source: {duration_seconds: 4}};
      } else {
        if (failPoll) throw Error('network');
        payload = current || {detail: 'missing'};
        if (!current) code = 404;
      }
      return {ok: code === 200, status: code, json: async () => structuredClone(payload)};
    },
  };
  vm.runInNewContext(source, context, {filename: 'video-edit.js'});
  const find = (tag, text) => nodes.find(node => node.tag === tag && (text === undefined || node.textContent === text));
  return {
    window, nodes, requests, timers, storage, events, find,
    state: value => { current = value; },
    errors: ({poll = false, cancel = false, discovery = false}) => {failPoll = poll; failCancel = cancel; failDiscovery = discovery;},
    get creates() { return creates; },
    async tick() { const [key, fn] = [...timers][0] || []; if (fn) { timers.delete(key); await fn(); await settle(); } },
  };
}

test('reload discovers backend job, shows phase steps, closes and reopens without cancelling', async () => {
  const b = browser({job: active({phase_progress: 0.25, current_step: 2, total_steps: 8})});
  await settle();
  assert.equal(b.find('progress').value, 0.25);
  assert.match(b.nodes.find(n => n.className === 'nobby-video-edit-status').textContent, /2\/8.*Teilphase/);
  assert.match(b.nodes.find(n => n.className === 'nobby-video-edit-hint' && n.textContent?.includes('Laufzeit')).textContent, /Laufzeit/);
  const cancel = b.find('button', 'Bearbeitung abbrechen');
  assert.equal(cancel.hidden, false);
  await b.window.MLXVideoEdit.open({kind: 'video', id});
  b.find('button', '×').listeners.click();
  assert.equal(b.requests.some(r => r.url.includes('/cancel')), false);
  const resume = b.find('button', 'Video-Editor öffnen');
  assert.equal(resume.hidden, false);
  resume.listeners.click();
  assert.equal(b.nodes.find(n => n.className === 'nobby-video-edit').hidden, false);
  await cancel.listeners.click();
  assert.equal(cancel.disabled, true);
  assert.match(b.nodes.find(n => n.className === 'nobby-video-edit-status').textContent, /Wird beendet/);
  await settle();
  b.state(active({status: 'cancelled', cancel_requested: true}));
  await b.tick();
  assert.equal(cancel.hidden, true);
  assert.match(b.nodes.find(n => n.className === 'nobby-video-edit-status').textContent, /Abgebrochen/);
  assert.equal(b.storage.has('mlx-video-edit-active-v1'), false);
});

test('unknown progress stays indeterminate; failed polling resumes and cancellation can be retried', async () => {
  const b = browser({job: active()});
  await settle();
  assert.equal(b.find('progress').value, undefined);
  b.errors({poll: true});
  await b.tick();
  assert.match(b.nodes.find(n => n.className === 'nobby-video-edit-status').textContent, /Statusabfrage fehlgeschlagen/);
  assert.ok(b.timers.size);
  b.errors({cancel: true});
  const cancel = b.find('button', 'Bearbeitung abbrechen');
  await cancel.listeners.click();
  assert.equal(cancel.disabled, false);
  b.errors({});
  await b.tick();
  await cancel.listeners.click();
  await cancel.listeners.click();
  assert.equal(b.requests.filter(r => r.url.includes('/cancel')).length, 2);
});

test('remembered job completed during reload restores its result and clears active storage', async () => {
  const b = browser({job: active({status: 'completed', result: {video_url: '/result.mp4'}}),
    saved: JSON.stringify({version: 1, id})});
  await settle();
  assert.equal(b.find('video').src, '/result.mp4');
  assert.equal(b.find('video').hidden, false);
  assert.equal(b.storage.size, 0);
});

test('corrupt or unavailable storage still discovers backend jobs', async () => {
  for (const options of [{saved: '{broken'}, {brokenStorage: true}, {saved: JSON.stringify({version: 1, id: '../bad'})}]) {
    const b = browser({job: active(), ...options});
    await settle();
    assert.equal(b.find('button', 'Bearbeitung abbrechen').hidden, false);
  }
});

test('job start prevents duplicate submits, and other tabs reconnect through discovery', async () => {
  const b = browser();
  await settle();
  await b.window.MLXVideoEdit.open({kind: 'video', id});
  b.find('textarea').value = 'Continue the motion';
  const form = b.find('form');
  const first = form.listeners.submit({preventDefault() {}});
  const second = form.listeners.submit({preventDefault() {}});
  await Promise.all([first, second]);
  assert.equal(b.creates, 1);
  const tab = browser({job: active(), saved: b.storage.get('mlx-video-edit-active-v1')});
  await settle();
  assert.equal(tab.find('button', 'Bearbeitung abbrechen').hidden, false);
  tab.state(active({status: 'completed', result: {video_url: '/done.mp4'}}));
  await tab.tick();
  assert.equal(tab.find('video').src, '/done.mp4');
});
