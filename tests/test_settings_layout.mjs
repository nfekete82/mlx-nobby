import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/settings-layout.js', import.meta.url),
    'utf8',
);

const window = {};
window.window = window;

const document = {
    readyState: 'loading',
    addEventListener() {},
};

const context = {
    window,
    document,
    navigator: { language: 'en-US' },
    location: { pathname: '/chat' },
    console,
    Array,
    String,
    Object,
    Promise,
    Error,
    RegExp,
    setTimeout() { return 1; },
    clearTimeout() {},
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/settings-layout.js',
});

const api = window.MLXSettingsLayout;
assert.equal(typeof api?.sectionFromPath, 'function');
assert.equal(typeof api?.systemTabFromPath, 'function');
assert.equal(typeof api?.sectionTarget, 'function');
assert.equal(typeof api?.activateModel, 'function');

assert.equal(api.sectionFromPath('/settings/general'), 'chat');
assert.equal(api.sectionFromPath('/settings/advanced/generation'), 'chat');
assert.equal(api.sectionFromPath('/settings/models'), 'models');
assert.equal(api.sectionFromPath('/settings/knowledge'), 'knowledge');
assert.equal(api.sectionFromPath('/settings/profile'), 'personal');
assert.equal(api.sectionFromPath('/settings/appearance'), 'personal');
assert.equal(api.sectionFromPath('/settings/functions'), 'tools');
assert.equal(api.sectionFromPath('/settings/automations'), 'automations');
assert.equal(api.sectionFromPath('/settings/advanced/runtime'), 'models');
assert.equal(api.sectionFromPath('/settings/advanced/storage'), 'models');
assert.equal(api.sectionFromPath('/settings/advanced/server'), 'system');
assert.equal(api.sectionFromPath('/settings/advanced/logs'), 'system');

assert.equal(api.systemTabFromPath('/settings/advanced/runtime'), null);
assert.equal(api.systemTabFromPath('/settings/advanced/storage'), null);
assert.equal(api.systemTabFromPath('/settings/advanced/server'), 'server');
assert.equal(api.systemTabFromPath('/settings/advanced/logs'), 'logs');
assert.equal(api.systemTabFromPath('/settings/models'), null);

assert.equal(api.sectionTarget('chat'), 'general');
assert.equal(api.sectionTarget('personal'), 'profile');
assert.equal(api.sectionTarget('tools'), 'functions');
assert.equal(api.sectionTarget('knowledge'), 'knowledge');
assert.equal(api.sectionTarget('models'), 'models');
assert.equal(api.sectionTarget('automations'), 'automations');

console.log('Organized settings navigation helpers passed.');
