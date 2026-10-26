import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const code = fs.readFileSync(new URL('../frontend/assets/chat/eml-batch.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');
const attachments = fs.readFileSync(new URL('../frontend/assets/chat/attachments.js', import.meta.url), 'utf8');
const generation = fs.readFileSync(new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8');

function harness(failAt = 0, mergeFails = false) {
    const controls = new Map();
    const control = id => {
        if (!controls.has(id)) controls.set(id, {
            value: '', hidden: true, textContent: '', listeners: {},
            addEventListener(name, fn) {this.listeners[name] = fn;}
        });
        return controls.get(id);
    };
    const pending = [];
    const removed = [];
    const calls = [];
    const events = [];
    let uploads = 0;
    let faqEnabled = false;
    let mergeStarted = false;
    const fixedId = '11223344556677889900aabbccddeeff';
    const sandbox = {
        window: {
            crypto: {randomUUID: () => '11223344-5566-7788-9900-aabbccddeeff'},
            MLXI18n: {t: (_key, fallback) => fallback},
            MLXChatAttachments: {
                removeAttachments(items) {
                    for (const item of items) {
                        const index = pending.indexOf(item);
                        if (index >= 0) pending.splice(index, 1);
                        removed.push(item);
                    }
                }
            }
        },
        document: {getElementById: control},
        FormData: class {
            constructor() {this.fields = {};}
            append(field, value, filename) {this.fields[field] = value; if (filename) this.filename = filename;}
        },
        setTimeout: callback => { callback(); },
        fetch: async (url, args = {}) => {
            calls.push({url, args});
            if (url.endsWith('/upload')) {
                uploads++;
                if (uploads === failAt) return {
                    ok: false, status: 500, json: async () => ({detail: 'test failure'})
                };
                return {ok: true, json: async () => ({accepted: true})};
            }
            if (url.endsWith('/start')) {
                faqEnabled = JSON.parse(args.body).create_faq === true;
                return {ok: true, json: async () => ({running: true})};
            }
            if (url.endsWith('/batch/' + fixedId + '/consolidate')) {
                if (mergeFails) return {ok: false, status: 503,
                    json: async () => ({detail: 'Local model unavailable'})};
                mergeStarted = true;
                return {ok: true, json: async () => ({state: 'processing'})};
            }
            if (url.endsWith('/batch/' + fixedId + '/status')) {
                return {ok: true, json: async () => ({
                    total: uploads, completed: uploads, failed: 0,
                    running: false, finished: true, faq_requested: faqEnabled,
                    faq_ready: faqEnabled ? uploads : 0, faq_failed: 0,
                    faq_merge_state: mergeStarted ? 'ready' : 'not_started'
                })};
            }
            throw Error('Unexpected endpoint ' + url);
        }
    };
    vm.runInNewContext(code, sandbox, {filename: 'eml-batch.js'});
    function addEml(name) {
        const file = {name, size: 1024, lastModified: 42};
        const item = {name, size: file.size, kind: 'eml', file};
        pending.push(item);
        return item;
    }
    return {eml: sandbox.window.MLXChatEml, calls, controls: control,
            pending, removed, addEml, events, fixedId};
}

test('normal chat boot makes no EML requests or redundant folder menu', () => {
    const h = harness();
    assert.equal(h.calls.length, 0);
    assert.ok(!html.includes('id="chatPickFolder"'));
    assert.ok(!html.includes('id="chatFolderFiles"'));
    assert.ok(!html.includes('emlChatTray'));
    assert.match(html, /data-plus-action="file"/);
});

test('ordinary file picker keeps EML chips; dropping a folder scans entries', () => {
    assert.match(html, /id="fileInput"[\s\S]*?accept="[^"]*\.eml"/);
    assert.match(attachments, /'pdf',\s*'eml'/);
    assert.match(attachments, /kind: 'eml'/);
    assert.match(attachments, /file, context_omitted: true/);
    assert.match(attachments, /file\.kind !== 'image' && file\.kind !== 'eml'/);
    assert.match(attachments, /webkitGetAsEntry\?\.\(\)/);
    assert.match(attachments, /reader\.readEntries/);
    assert.match(attachments, /collectDroppedEntries\(event\.dataTransfer\)/);
    assert.match(generation, /const emlAttachments = currentAttachments\.filter/);
    assert.ok(generation.indexOf('const emlAttachments =') <
        generation.indexOf('const imageFiles =', generation.indexOf('async function sendMessage')));
});

test('100 EMLs processed via one chat prompt; exact scoped ZIP returned in chat', async () => {
    const h = harness();
    for (let i = 0; i < 100; i++) h.addEml('mail-' + i + '.eml');
    const rejected = await h.eml.submit('Fasse die E-Mails zusammen', h.pending);
    assert.equal(rejected.imported, 0);
    assert.equal(h.calls.length, 0);
    const result = await h.eml.submit('Anonymisiere diese EML-Dateien', h.pending,
        event => h.events.push(event));
    assert.equal(result.success, true);
    assert.equal(result.finished, true);
    assert.equal(result.completed, 100);
    assert.equal(result.imported, 100);
    assert.equal(result.downloadUrl, '/api/eml-anonymizer/batch/' + h.fixedId + '/export');
    assert.equal(h.calls.filter(x => x.url.endsWith('/upload')).length, 100);
    assert.equal(h.calls.filter(x => x.url.endsWith('/start')).length, 1);
    assert.equal(h.calls.filter(x => x.url.endsWith('/status')).length, 1);
    assert.equal(h.pending.length, 0);
    assert.equal(h.removed.length, 100);
    assert.equal(h.events[0].phase, 'upload');
    assert.equal(h.events.at(-1).completed, 100);
    const uploads = h.calls.filter(x => x.url.endsWith('/upload'));
    assert.ok(uploads.every(x => x.args.body.fields.batch_id === h.fixedId));
    assert.ok(h.calls.every(x => !x.url.includes('/chat/completions')));
});

test('single EML with local AI returns single output file path', async () => {
    const h = harness();
    h.addEml('one.eml');
    const result = await h.eml.submit('Anonymisiere diese EML mit lokaler KI', h.pending);
    assert.equal(result.success, true);
    assert.equal(result.downloadUrl, '/api/eml-anonymizer/batch/' + h.fixedId + '/result');
    assert.equal(JSON.parse(h.calls.find(x => x.url.endsWith('/start')).args.body).use_local_ai, true);
    assert.equal(h.eml.__test.useLocalAI('Anonymisieren ohne KI'), false);
    assert.equal(h.eml.__test.useLocalAI('mit der lokalen KI'), true);
});

test('partial error preserves only unuploaded attachments for retry', async () => {
    const h = harness(2);
    ['first.eml', 'second.eml', 'third.eml'].forEach(h.addEml);
    const result = await h.eml.submit('Anonymisiere diese E-Mails', h.pending);
    assert.equal(result.success, false);
    assert.equal(result.imported, 1);
    assert.equal(h.pending.length, 2);
    assert.equal(h.calls.filter(x => x.url.endsWith('/start')).length, 0);
    const retry = await h.eml.submit('Anonymisiere diese E-Mails', h.pending);
    assert.equal(retry.success, true);
    assert.equal(retry.imported, 2);
    assert.equal(h.pending.length, 0);
    assert.deepEqual(h.calls.filter(x => x.url.endsWith('/upload')).map(x => x.args.body.filename),
        ['first.eml', 'second.eml', 'second.eml', 'third.eml']);
});

test('chat displays inline in-progress message and renders downloadable link', () => {
    assert.match(generation, /role: 'assistant',\s*content: gt\('eml_uploading'/);
    assert.match(generation, /const onProgress = state =>/);
    assert.match(generation, /eml_processing/);
    assert.match(generation, /result\.downloadUrl/);
    assert.match(generation, /MLXChatRendering\.renderAll\(\{contentUpdated: true\}\)/);
    assert.match(generation, /eml_review_warning/);
    assert.match(generation, /window\.MLXChatEml\.submit\(prompt, emlAttachments, onProgress\)/);
});


test('a single FAQ prompt requests redaction followed by local FAQ generation', async () => {
    const h = harness();
    h.addEml('support.eml');
    assert.equal(h.eml.__test.wantsFAQ('Erstelle daraus eine FAQ'), true);
    assert.equal(h.eml.__test.wantsRedaction('Fasse die EML-Dateien als FAQ zusammen'), true);
    const result = await h.eml.submit('Bitte E-Mails anonymisieren und als FAQ zusammenfassen', h.pending);
    assert.equal(result.success, true);
    assert.equal(result.faqRequested, true);
    assert.equal(result.faqReady, 1);
    assert.equal(result.faqUrl, '/api/eml-anonymizer/batch/' + h.fixedId + '/faq');
    assert.equal(h.calls.filter(x => x.url.endsWith('/consolidate')).length, 1);
    assert.equal(result.downloadUrl, '/api/eml-anonymizer/batch/' + h.fixedId + '/result');
    const request = h.calls.find(x => x.url.endsWith('/start'));
    const data = JSON.parse(request.args.body);
    assert.equal(data.create_faq, true);
    assert.equal(data.batch_id, h.fixedId);
    assert.equal(data.use_local_ai, true);
    assert.match(generation, /result\.faqUrl/);
    assert.match(generation, /eml_processing_faq/);
    assert.match(generation, /eml_faq_unavailable/);
});


test('FAQ consolidation error preserves anonymized source files and explains missing FAQ', async () => {
    const h = harness(0, true);
    h.addEml('case.eml');
    const result = await h.eml.submit('Erstelle eine anonymisierte FAQ', h.pending);
    assert.equal(result.success, true);
    assert.equal(result.finished, true);
    assert.equal(result.faqUrl, '');
    assert.match(result.faqMergeError, /Local model unavailable/);
    assert.equal(result.downloadUrl, '/api/eml-anonymizer/batch/' + h.fixedId + '/result');
    assert.equal(h.calls.filter(x => x.url.endsWith('/consolidate')).length, 1);
    assert.match(generation, /result\.faqMergeError/);
    assert.match(generation, /eml_sources_optional/);
    assert.match(generation, /eml_merging_faq/);
});
