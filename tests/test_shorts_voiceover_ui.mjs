import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../frontend/assets/chat/shorts-history.js', import.meta.url), 'utf8');
const translations = JSON.parse(fs.readFileSync(new URL('../frontend/i18n/shorts-studio.json', import.meta.url), 'utf8'));
function setup(lang) {
    const window = { __MLXShortsStudioTranslations: translations };
    const element = () => ({children: [], appendChild(child) {this.children.push(child);}});
    const document = {readyState: 'loading', addEventListener() {}, documentElement: {lang},
        createElement: element};
    vm.runInNewContext(source, {window, document, console});
    return {history: window.MLXShortsHistory, element};
}
const job = {status: 'failed', error_stage: 'tts', error_code: 'VOICEOVER_TOO_LONG',
    error_scene_number: 2, error_audio_duration: 7.8, error_scene_duration: 5};

for (const lang of ['de', 'en']) {
    test(`known duration error renders localized safe message (${lang})`, () => {
        const {history, element} = setup(lang);
        const parent = element();
        history.renderJobStatus(parent, job);
        const message = parent.children.find(child => child.className === 'mlx-shorts-history-error').textContent;
        assert.match(message, lang === 'de' ? /Szene 2.*7,8 s.*5,0 s/ : /scene 2.*7.8 s.*5.0 s/);
        assert.match(message, lang === 'de' ? /Text kürzen/ : /shorten the text/);
    });
}
test('unknown and malformed duration errors retain generic safe fallback', () => {
    const {history, element} = setup('de');
    for (const error of [{error_code: 'UNKNOWN'}, {error_audio_duration: '<secret>'}]) {
        const parent = element();
        history.renderJobStatus(parent, {...job, ...error, error: 'Traceback /private/secret', error_detail_safe: '/private/secret', error_provider: '/private/secret', error_model: '/private/secret'});
        const message = parent.children.find(child => child.className === 'mlx-shorts-history-error').textContent;
        assert.equal(message, translations.de.history_error_tts);
        assert.ok(!JSON.stringify(parent).includes('secret'));
    }
});
