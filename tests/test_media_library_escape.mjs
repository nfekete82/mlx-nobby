import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the library's real Escape handlers without a browser or API services.
const source = fs.readFileSync(
  new URL('../frontend/assets/chat/media-library.js', import.meta.url), 'utf8'
);
const keyboardHandlers = [...source.matchAll(
  /document\.addEventListener\("keydown", event => \{\n[\s\S]*?\n  \}\);/g
)].map(match => match[0]);
assert.equal(keyboardHandlers.length, 2, 'Preview and library Escape handlers must be present');

function makeHarness() {
  const handlers = [];
  const preview = {hidden: false};
  const panel = {hidden: false};
  const shell = {};
  let previewsClosed = 0;
  let fullscreenExits = 0;
  let libraryCloses = 0;
  const document = {
    fullscreenElement: null,
    activeElement: null,
    addEventListener(type, handler) {
      assert.equal(type, 'keydown');
      handlers.push(handler);
    },
    exitFullscreen() {
      fullscreenExits++;
      this.fullscreenElement = null;
      return Promise.resolve();
    }
  };
  vm.runInNewContext(keyboardHandlers.join('\n'), {
    document, preview, panel, shell,
    previewClose: {}, previewFull: {},
    previewBody: {querySelectorAll: () => []},
    closePreview() {
      previewsClosed++;
      preview.hidden = true;
    },
    setVisible(visible) {
      libraryCloses++;
      panel.hidden = !visible;
    }
  });
  function pressEscape(repeat = false) {
    const event = {
      key: 'Escape',
      repeat,
      defaultPrevented: false,
      immediateStopped: false,
      preventDefault() { this.defaultPrevented = true; },
      stopImmediatePropagation() { this.immediateStopped = true; }
    };
    for (const handler of handlers) {
      if (event.immediateStopped) break;
      handler(event);
    }
    return event;
  }
  return {
    preview, panel, shell, document, pressEscape,
    get previewsClosed() { return previewsClosed; },
    get fullscreenExits() { return fullscreenExits; },
    get libraryCloses() { return libraryCloses; }
  };
}

for (const kind of ['image', 'video']) {
  const h = makeHarness();
  const first = h.pressEscape();
  assert.ok(first.defaultPrevented && first.immediateStopped, kind + ': Escape is consumed');
  assert.equal(h.previewsClosed, 1, kind + ': preview closes');
  assert.equal(h.preview.hidden, true);
  assert.equal(h.panel.hidden, false, kind + ': library stays open');
  h.pressEscape(true);
  assert.equal(h.libraryCloses, 0, kind + ': held Escape cannot close library');
  h.pressEscape();
  assert.equal(h.libraryCloses, 1, kind + ': next press closes library');
  assert.equal(h.panel.hidden, true);
}

const full = makeHarness();
full.document.fullscreenElement = full.shell;
full.pressEscape();
assert.equal(full.fullscreenExits, 1, 'First Escape exits native fullscreen');
assert.equal(full.preview.hidden, false, 'Fullscreen exit leaves preview open');
assert.equal(full.panel.hidden, false, 'Fullscreen exit leaves library open');
full.pressEscape();
assert.equal(full.previewsClosed, 1, 'Second Escape closes preview');
assert.equal(full.panel.hidden, false);
full.pressEscape();
assert.equal(full.panel.hidden, true, 'Third Escape closes library');

const gallery = makeHarness();
gallery.preview.hidden = true;
gallery.pressEscape();
assert.equal(gallery.panel.hidden, true, 'Escape from gallery closes library');

const inactive = makeHarness();
inactive.preview.hidden = true;
inactive.panel.hidden = true;
inactive.pressEscape();
assert.equal(inactive.libraryCloses, 0, 'Escape does nothing if library is closed');

console.log('Media library Escape closes fullscreen, preview, then gallery one level per press.');
