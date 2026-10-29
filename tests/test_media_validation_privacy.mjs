import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const window = {MLXI18n: {t: (_key, fallback) => fallback}};
window.window = window;
vm.runInNewContext(fs.readFileSync(new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8'), {
    window, document: {addEventListener() {}, getElementById() {return null;}}, console,
});
const api = window.MLXChatGeneration;
const invalid = 'Die Bildanfrage ist ungültig. Bitte Modell, Bildgröße, Parameter und Referenzbild prüfen.';
const detail = [{type: 'value_error', input: {source_path: '/private/uploads/source.png', metadata: 'private'}}];

test('image HTTP validation never reads or displays the raw response body', async () => {
    for (const status of [400, 422]) {
        const error = await api.__test.imageResponseError({status,
            text: async () => {throw Error('Must not read private body');}});
        assert.equal(error.message, invalid);
        const known = await api.__test.imageResponseError({status, json: async () => ({detail: 'Ungültige Image-Job-ID'})});
        assert.equal(known.message, 'Ungültige Image-Job-ID');
    }
});

test('legacy image validation objects and Python bodies are compact in job cards', () => {
    for (const error of [detail, JSON.stringify({detail}), '1 validation error for Generate\ninput_value=/private/source.png', 'Traceback /Users/private']) {
        assert.equal(api.__test.publicImageJobError(error), invalid);
        const message = {};
        api.updateImageJobMessage({}, message, {tool: 'image_generate', status: 'failed', error,
            data: {job: {id: 'a'.repeat(24), status: 'failed', error}}});
        assert.equal(message.image_job.error, invalid);
        assert.doesNotMatch(message.content, /\/private|\/Users|input_value|Traceback/);
    }
    assert.equal(api.__test.publicImageJobError('Bildauftrag abgebrochen'), 'Bildauftrag abgebrochen');
});

test('legacy video Pydantic error strings cannot expose validator inputs', () => {
    assert.doesNotMatch(api.__test.publicVideoJobError('1 validation error for JobCreate\n/private/uploads/secret.png'), /\/private|validation error/);
});
