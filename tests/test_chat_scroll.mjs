import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';


class FakeClassList {
    constructor() {
        this.values = new Set();
    }

    toggle(name, force) {
        if (force) this.values.add(name);
        else this.values.delete(name);
    }

    contains(name) {
        return this.values.has(name);
    }
}


class FakeElement {
    constructor(id = '') {
        this.id = id;
        this.style = {};
        this.classList = new FakeClassList();
        this.listeners = new Map();
        this.attributes = new Map();
        this.children = [];
        this.parentElement = null;
        this.clientHeight = 0;
        this.scrollHeight = 0;
        this._scrollTop = 0;
        this.checked = true;
    }

    get scrollTop() {
        return this._scrollTop;
    }

    set scrollTop(value) {
        this._scrollTop = Math.max(
            0,
            Math.min(
                Number(value) || 0,
                Math.max(0, this.scrollHeight - this.clientHeight)
            )
        );
    }

    addEventListener(type, listener) {
        const listeners = this.listeners.get(type) || [];
        listeners.push(listener);
        this.listeners.set(type, listeners);
    }

    dispatch(type) {
        for (const listener of this.listeners.get(type) || []) {
            listener({ target: this });
        }
    }

    appendChild(child) {
        child.parentElement = this;
        this.children.push(child);
        return child;
    }

    setAttribute(name, value) {
        this.attributes.set(name, String(value));
    }

    userScrollTo(value) {
        this.scrollTop = value;
        this.dispatch('scroll');
    }
}


function createRuntimeHarness() {
    const frameCallbacks = new Map();
    let nextFrameId = 1;
    const elements = new Map();
    const main = new FakeElement('main');
    const messages = new FakeElement('messages');
    messages.parentElement = main;
    messages.clientHeight = 400;
    messages.scrollHeight = 1000;
    messages.scrollTop = 600;
    elements.set('messages', messages);

    globalThis.requestAnimationFrame = callback => {
        const id = nextFrameId++;
        frameCallbacks.set(id, callback);
        return id;
    };
    globalThis.cancelAnimationFrame = id => {
        frameCallbacks.delete(id);
    };
    globalThis.setInterval = () => 0;
    globalThis.clearInterval = () => {};
    globalThis.window = {
        addEventListener() {}
    };
    globalThis.document = {
        getElementById(id) {
            if (!elements.has(id)) {
                elements.set(id, new FakeElement(id));
            }
            return elements.get(id);
        },
        createElement() {
            return new FakeElement();
        }
    };

    const source = fs.readFileSync(
        new URL('../frontend/assets/chat/runtime.js', import.meta.url),
        'utf8'
    );
    vm.runInThisContext(source, {
        filename: 'frontend/assets/chat/runtime.js'
    });

    function flushFrames(limit = 8) {
        for (let frame = 0; frame < limit; frame++) {
            if (!frameCallbacks.size) break;
            const callbacks = [...frameCallbacks.values()];
            frameCallbacks.clear();
            callbacks.forEach(callback => callback());
        }
    }

    function renderUpdate(scrollHeight, contentUpdated = true) {
        const snapshot = window.MLXChatRuntime.beforeMessagesRender();
        messages.scrollHeight = scrollHeight;
        window.MLXChatRuntime.afterMessagesRender(
            snapshot,
            { contentUpdated }
        );
        flushFrames();
    }

    return {
        runtime: window.MLXChatRuntime,
        messages,
        button: main.children[0],
        flushFrames,
        renderUpdate
    };
}


test('chat follows only while the user remains at the bottom', () => {
    const {
        runtime,
        messages,
        button,
        flushFrames,
        renderUpdate
    } = createRuntimeHarness();

    runtime.resetScrollForChat();
    renderUpdate(1200);
    assert.equal(messages.scrollTop, 800);

    messages.userScrollTo(300);
    renderUpdate(1400);
    assert.equal(messages.scrollTop, 300);
    assert.equal(button.classList.contains('visible'), true);

    // Agent/status or Markdown updates may change content without increasing
    // the measured height; the user's reading position must still be stable.
    renderUpdate(1400);
    assert.equal(messages.scrollTop, 300);
    assert.equal(button.classList.contains('visible'), true);

    messages.userScrollTo(1000);
    flushFrames();
    assert.equal(button.classList.contains('visible'), false);
    renderUpdate(1500);
    assert.equal(messages.scrollTop, 1100);

    // Even an upward gesture inside the 88 px bottom tolerance disables
    // following immediately.
    messages.userScrollTo(1050);
    renderUpdate(1550);
    assert.equal(messages.scrollTop, 1050);
    assert.equal(button.classList.contains('visible'), true);

    button.dispatch('click');
    flushFrames();
    assert.equal(messages.scrollTop, 1150);
    assert.equal(button.classList.contains('visible'), false);

    messages.userScrollTo(500);
    runtime.beginUserMessage();
    renderUpdate(1650);
    flushFrames();
    assert.equal(messages.scrollTop, 1250);
    assert.equal(button.classList.contains('visible'), false);
    assert.equal(
        button.attributes.get('aria-label'),
        'Jump to new messages'
    );
});


test('user input wins over a pending programmatic scroll guard', () => {
    const {
        runtime,
        messages,
        flushFrames,
        renderUpdate
    } = createRuntimeHarness();

    runtime.resetScrollForChat();
    renderUpdate(1000);

    const snapshot = runtime.beforeMessagesRender();
    messages.scrollHeight = 1100;
    runtime.afterMessagesRender(
        snapshot,
        { contentUpdated: true }
    );

    // Execute the scheduled automatic scroll, but not both guard-release
    // animation frames.
    flushFrames(1);
    assert.equal(messages.scrollTop, 700);

    messages.userScrollTo(500);
    flushFrames();
    renderUpdate(1200);

    assert.equal(messages.scrollTop, 500);
});
