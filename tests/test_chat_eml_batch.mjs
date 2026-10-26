import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const code = fs.readFileSync(new URL('../frontend/assets/chat/eml-batch.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');
const attachments = fs.readFileSync(new URL('../frontend/assets/chat/attachments.js', import.meta.url), 'utf8');
const generation = fs.readFileSync(new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8');

function harness(failAt = 0) {
    const controls = new Map();
    const control = id => {
        if (!controls.has(id)) {
            controls.set(id, {
                hidden: true, value: '', disabled: false, checked: false,
                textContent: '', listeners: {},
                addEventListener(name, fn) { this.listeners[name] = fn; },
                dispatchEvent() {}, click() {}
            });
        }
        return controls.get(id);
    };
    let uploads = 0;
    const calls = [];
    const sandbox = {
        window: {MLXI18n: {t: (_key, fallback) => fallback}},
        document: {getElementById: control},
        Event: class { constructor(name) {this.type = name;} },
        FormData: class {
            append(field, file, filename) {this.field = field; this.file = file; this.filename = filename;}
        },
        fetch: async (url, args = {}) => {
            calls.push({url, args});
            if (url.endsWith('/upload')) {
                uploads++;
                if (uploads === failAt) return {ok: false, status: 500, json: async () => ({detail: 'test failure'})};
                return {ok: true, json: async () => ({accepted: true})};
            }
            if (url.endsWith('/status')) return {ok: true, json: async () => ({
                counts: {queued: uploads, processing: 0, review: 0, failed: 0}
            })};
            if (url.endsWith('/start')) return {ok: true, json: async () => ({running: true})};
            throw Error('Unexpected endpoint ' + url);
        },
        setInterval() {},
    };
    vm.runInNewContext(code, sandbox, {filename: 'eml-batch.js'});
    return {eml: sandbox.window.MLXChatEml, controls: control, calls,
        file: (name, size = 1024) => ({name, size, lastModified: 42})};
}

test('regular chat picker and drop handler pass EMLs only to queue staging', () => {
    assert.match(html, /id="emlChatPickFiles"/);
    assert.match(html, /id="emlChatPickFolder"/);
    assert.match(html, /id="emlChatFolder"[^>]*webkitdirectory/);
    assert.match(html, /id="fileInput"[\s\S]*?accept="[^"]*\.eml"/);
    assert.match(attachments, /window\.MLXChatEml\?\.stageFiles\(emls\)/);
    assert.match(generation, /window\.MLXChatEml\?\.hasStaged\?\.\(\)/);
    assert.ok(generation.indexOf('window.MLXChatEml?.hasStaged?.()') <
        generation.indexOf('const imageFiles =', generation.indexOf('async function sendMessage')));
});

test('100 EMLs upload one request at a time after explicit prompt, no model calls', async () => {
    const h = harness();
    const files = Array.from({length: 100}, (_, i) => h.file('mail-' + i + '.eml'));
    const stats = h.eml.stageFiles(files);
    assert.equal(stats.accepted, 100);
    assert.equal(h.controls('input').value, 'Anonymisiere diese EML-Dateien.');
    assert.equal(h.controls('emlChatTray').hidden, false);
    let result = await h.eml.submit('Bitte beantworte diese Mail');
    assert.equal(result.success, false);
    assert.equal(h.calls.filter(x => x.url.endsWith('/upload')).length, 0);
    h.controls('emlChatAI').checked = true;
    result = await h.eml.submit('Anonymisiere diese 100 EML-Dateien.');
    assert.equal(result.success, true);
    assert.equal(result.imported, 100);
    assert.equal(h.eml.hasStaged(), false);
    assert.equal(h.calls.filter(x => x.url.endsWith('/upload')).length, 100);
    assert.equal(h.calls.filter(x => x.url.endsWith('/start')).length, 1);
    const started = h.calls.find(x => x.url.endsWith('/start'));
    assert.equal(JSON.parse(started.args.body).use_local_ai, true);
    assert.equal(h.calls.some(x => /\/chat|\/route|\/mlx/.test(x.url)), false);
});

test('unsupported, duplicate and oversized files never enter queue', () => {
    const h = harness();
    const stats = h.eml.stageFiles([
        h.file('ok.EML'), h.file('ok.EML'), h.file('not.pdf'),
        h.file('large.eml', 31 * 1024 * 1024)
    ]);
    assert.equal(stats.accepted, 1);
    assert.equal(stats.rejected, 2);
    assert.equal(h.eml.__test.pendingCount(), 1);
    h.eml.__test.clear();
    assert.equal(h.eml.hasStaged(), false);
});

test('partial upload failure retains remaining files and never retries imported files', async () => {
    const h = harness(2);
    h.eml.stageFiles([h.file('first.eml'), h.file('second.eml'), h.file('third.eml')]);
    const result = await h.eml.submit('Anonymisiere diese E-Mails');
    assert.equal(result.success, false);
    assert.equal(result.imported, 1);
    assert.equal(result.total, 3);
    assert.equal(h.eml.__test.pendingCount(), 2);
    assert.equal(h.calls.filter(x => x.url.endsWith('/start')).length, 0);
    const retry = await h.eml.submit('Anonymisiere die übrigen E-Mails');
    assert.equal(retry.success, true);
    assert.equal(retry.imported, 2);
    assert.equal(h.eml.__test.pendingCount(), 0);
    assert.deepEqual(h.calls.filter(x => x.url.endsWith('/upload'))
        .map(x => x.args.body.filename), ['first.eml', 'second.eml', 'second.eml', 'third.eml']);
});
