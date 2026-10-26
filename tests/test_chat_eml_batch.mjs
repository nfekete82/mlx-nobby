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
                value: '', listeners: {}, clickCount: 0,
                addEventListener(name, fn) { this.listeners[name] = fn; },
                click() { this.clickCount++; },
            });
        }
        return controls.get(id);
    };
    const pending = [];
    const removed = [];
    const calls = [];
    let uploads = 0;
    const sandbox = {
        window: {MLXChatAttachments: {
            addFiles: files => {pending.push(...files);},
            removeAttachments: files => {
                for (const file of files) {
                    const index = pending.indexOf(file);
                    if (index >= 0) pending.splice(index, 1);
                    removed.push(file);
                }
            },
        }},
        document: {getElementById: control},
        FormData: class {
            append(field, file, filename) {this.field = field; this.file = file; this.filename = filename;}
        },
        fetch: async (url, args = {}) => {
            calls.push({url, args});
            if (url.endsWith('/upload')) {
                uploads++;
                if (uploads === failAt) return {
                    ok: false, status: 500, json: async () => ({detail: 'test failure'})
                };
                return {ok: true, json: async () => ({accepted: true})};
            }
            if (url.endsWith('/start')) return {ok: true, json: async () => ({running: true})};
            throw Error('Unexpected endpoint ' + url);
        },
    };
    vm.runInNewContext(code, sandbox, {filename: 'eml-batch.js'});
    const file = (name, size = 1024) => ({
        name, size, lastModified: 42
    });
    function addEml(name) {
        const f = file(name);
        const item = {name, size: f.size, kind: 'eml', file: f};
        pending.push(item);
        return item;
    }
    return {eml: sandbox.window.MLXChatEml, controls: control, calls, pending, removed, file, addEml};
}

test('ordinary chat loads with no EML API requests', () => {
    const h = harness();
    assert.equal(h.calls.length, 0);
    assert.ok(!html.includes('emlChatTray'));
    assert.ok(!html.includes('emlChatPickFiles'));
    assert.ok(!html.includes('emlChatPickFolder'));
    assert.ok(!html.includes('href="/eml-anonymizer" role="menuitem"'));
});

test('standard chat file picker and drop create normal EML attachment chips', () => {
    assert.match(html, /id="fileInput"[\s\S]*?accept="[^"]*\.eml"/);
    assert.match(attachments, /'pdf',\s*'eml'/);
    assert.match(attachments, /kind: 'eml',/);
    assert.match(attachments, /file, context_omitted: true/);
    assert.match(attachments, /attachments\.filter\(\s*file => file\.kind !== 'image' && file\.kind !== 'eml'/);
    assert.match(attachments, /renderAttachments\(\)/);
    assert.match(html, /id="chatPickFolder"/);
    assert.match(html, /id="chatFolderFiles"[^>]*webkitdirectory/);
    assert.match(generation, /currentAttachments\.filter\(file => file\.kind === 'eml'\)/);
    assert.ok(generation.indexOf('const emlAttachments =') <
        generation.indexOf('const imageFiles =', generation.indexOf('async function sendMessage')));
});

test('100 ordinary EML file attachments dispatch to local batch without model requests', async () => {
    const h = harness();
    for (let i = 0; i < 100; i++) h.addEml('mail-' + i + '.eml');
    let result = await h.eml.submit('Bitte fasse diese E-Mails zusammen.', h.pending);
    assert.equal(result.success, false);
    assert.equal(result.imported, 0);
    assert.equal(h.calls.length, 0);
    result = await h.eml.submit('Anonymisiere diese 100 EML-Dateien.', h.pending);
    assert.equal(result.success, true);
    assert.equal(result.imported, 100);
    assert.equal(h.pending.length, 0);
    assert.equal(h.removed.length, 100);
    assert.equal(h.calls.filter(x => x.url.endsWith('/upload')).length, 100);
    assert.equal(h.calls.filter(x => x.url.endsWith('/start')).length, 1);
    assert.equal(h.calls.some(x => /\/chat|\/mlx|\/route/.test(x.url)), false);
    const start = h.calls.find(x => x.url.endsWith('/start'));
    assert.equal(JSON.parse(start.args.body).use_local_ai, false);
});

test('optional local AI is inferred from user prompt, not separate checkbox', async () => {
    const h = harness();
    h.addEml('one.eml');
    const result = await h.eml.submit('Bitte anonymisiere die EML mit lokaler KI.', h.pending);
    assert.equal(result.success, true);
    const start = h.calls.find(x => x.url.endsWith('/start'));
    assert.equal(JSON.parse(start.args.body).use_local_ai, true);
    assert.equal(h.eml.__test.useLocalAI('Anonymisieren ohne KI'), false);
});

test('folder option stages only EMLs into ordinary chat attachments', () => {
    const h = harness();
    const input = h.controls('chatFolderFiles');
    h.controls('chatPickFolder').listeners.click();
    assert.equal(input.clickCount, 1);
    input.listeners.change({target: {
        files: [h.file('a.eml'), h.file('secret.pdf'), h.file('b.EML')],
        value: 'previous'
    }});
    assert.equal(h.pending.length, 2);
    assert.equal(h.pending[0].name, 'a.eml');
    assert.equal(h.pending[1].name, 'b.EML');
});

test('partial upload failure keeps only unimported attachments for retry', async () => {
    const h = harness(2);
    h.addEml('first.eml');
    h.addEml('second.eml');
    h.addEml('third.eml');
    const result = await h.eml.submit('Anonymisiere diese E-Mails.', h.pending);
    assert.equal(result.success, false);
    assert.equal(result.imported, 1);
    assert.equal(result.total, 3);
    assert.equal(h.pending.length, 2);
    assert.equal(h.pending[0].name, 'second.eml');
    assert.equal(h.calls.filter(x => x.url.endsWith('/start')).length, 0);
    const retry = await h.eml.submit('Anonymisiere die verbleibenden Dateien.', h.pending);
    assert.equal(retry.success, true);
    assert.equal(retry.imported, 2);
    assert.equal(h.pending.length, 0);
    assert.deepEqual(h.calls.filter(x => x.url.endsWith('/upload'))
        .map(x => x.args.body.filename),
        ['first.eml', 'second.eml', 'second.eml', 'third.eml']);
});

test('mixed attachments are rejected before file or model routing', () => {
    assert.match(generation, /emlAttachments\.length !== currentAttachments\.length/);
    assert.match(generation, /window\.MLXChatEml\.submit\(prompt, emlAttachments\)/);
    assert.ok(!generation.includes('window.MLXChatEml?.hasStaged?.()'));
});
