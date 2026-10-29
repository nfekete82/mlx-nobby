import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');

class FakeNode {
  constructor(tagName = 'div') {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.className = '';
    this.textContent = '';
    this.style = {};
    this.attrs = {};
    this._innerHTML = '';
    this.parent = null;
  }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(value) {
    this._innerHTML = value;
    this.children.forEach(child => { child.parent = null; });
    this.children = [];
  }
  get lastElementChild() { return this.children.at(-1) || null; }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  replaceChild(child, existing) {
    const i = this.children.indexOf(existing);
    assert.notEqual(i, -1);
    this.children[i] = child;
    existing.parent = null;
    child.parent = this;
    return existing;
  }
  remove() {
    if (!this.parent) return;
    const i = this.parent.children.indexOf(this);
    if (i !== -1) this.parent.children.splice(i, 1);
    this.parent = null;
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  addEventListener() {}
  querySelectorAll(selector) { return []; }
  querySelector(selector) {
    if (selector === 'video.video-artifact-player') {
      const find = node =>
        (node.tagName === 'VIDEO' && node.className === 'video-artifact-player')
          ? node : node.children.map(find).find(Boolean);
      return find(this) || null;
    }
    return null;
  }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
}

function harness() {
  const messagesInner = new FakeNode('section');
  const document = {
    documentElement: {lang: 'de'},
    getElementById(id) { return id === 'messagesInner' ? messagesInner : null; },
    createElement(tagName) { return new FakeNode(tagName); },
    addEventListener() {},
  };
  let session = {
    id: 'session-1', messages: [{
      role: 'assistant', content: '',
      tool_result: {
        tool: 'video_generate', status: 'completed',
        artifacts: [{video_id: 'a'.repeat(24), model: 'ltx', mime_type: 'video/mp4'}],
      },
    }],
  };
  const window = {MLXI18n: {getLanguage: () => 'de'}};
  const context = {
    window, document, console, setInterval, clearInterval, setTimeout, clearTimeout,
    MLXChatRuntime: {
      beforeMessagesRender: () => ({}),
      afterMessagesRender() {},
      showGenerationMetrics: () => false,
      showRuntimeThinkingInfo: () => false,
    },
  };
  vm.runInNewContext(source, context, {filename: 'rendering.js'});
  const rendering = window.MLXChatRendering;
  rendering.configure({
    state: {}, currentSession: () => session, isGenerating: () => false,
    updateContext() {}, startEditMessage() {}, regenerateLastAnswer() {},
  });
  const player = () => messagesInner.children[0]?.querySelector('video.video-artifact-player');
  return {rendering, messagesInner, player, get session() {return session;},
          set session(value) {session = value;}, window};
}

test('playing chat video survives ordinary and unrelated-message rerenders', () => {
  const h = harness();
  h.rendering.renderMessages({contentUpdated: true});
  const article = h.messagesInner.children[0];
  const video = h.player();
  assert.ok(video, 'video card is rendered');
  video.currentTime = 2.7;
  video.paused = false;

  h.rendering.renderMessages({contentUpdated: false});
  assert.equal(h.messagesInner.children[0], article, 'same chat DOM article');
  assert.equal(h.player(), video, 'same HTMLVideoElement');
  assert.equal(h.player().currentTime, 2.7);

  h.session.messages.push({role: 'user', content: 'Hallo'});
  h.rendering.renderMessages({contentUpdated: true});
  assert.equal(h.messagesInner.children[0], article, 'video remains mounted on new chat message');
  assert.equal(h.player(), video);
  assert.equal(h.messagesInner.children.length, 2);
});

test('edited video messages, session changes and removals do not leak old video nodes', () => {
  const h = harness();
  h.rendering.renderMessages();
  const before = h.player();
  h.session.messages[0].content = 'Updated details';
  h.rendering.renderMessages();
  assert.notEqual(h.player(), before, 'changed message rerenders');

  const updated = h.player();
  h.session = {id: 'session-2', messages: structuredClone(h.session.messages)};
  h.rendering.renderMessages();
  assert.notEqual(h.player(), updated, 'other chat must use new player');

  h.session.messages = [{role: 'user', content: 'test'}, {role: 'user', content: 'end'}];
  h.rendering.renderMessages();
  assert.equal(h.player(), null);
  assert.equal(h.messagesInner.children.length, 2);
  h.session.messages.splice(1);
  h.rendering.renderMessages();
  assert.equal(h.messagesInner.children.length, 1, 'obsolete nodes are discarded');
});
