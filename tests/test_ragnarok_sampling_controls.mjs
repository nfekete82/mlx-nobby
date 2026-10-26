import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const html = fs.readFileSync('frontend/chat.html', 'utf8');
const css = fs.readFileSync('frontend/assets/chat.css', 'utf8');
const de = JSON.parse(fs.readFileSync('frontend/i18n/de.json', 'utf8'));
const en = JSON.parse(fs.readFileSync('frontend/i18n/en.json', 'utf8'));

const start = source.indexOf('const RAGNAROK_SAMPLING_PRESETS');
const end = source.indexOf('const IMAGE_SIZES_BY_FORMAT', start);
assert.ok(start >= 0 && end > start);
const env = vm.createContext({});
vm.runInContext(source.slice(start, end), env);
const preset = q => JSON.parse(JSON.stringify(env.ragnarokSamplingForQuality(q)));

test('Ragnarok quality presets expose exact steps and CFG', () => {
    assert.deepEqual(preset('fast'), {steps: 20, guidance: 4});
    assert.deepEqual(preset('standard'), {steps: 35, guidance: 4});
    assert.deepEqual(preset('quality'), {steps: 30, guidance: 4});
    assert.deepEqual(preset('ultra'), {steps: 40, guidance: 4});
    assert.deepEqual(preset('invalid'), preset('standard'));
});

test('expert input validation matches server schema and rejects empty/NaN values', () => {
    assert.deepEqual(
        JSON.parse(JSON.stringify(env.parseSamplingValues('38', '3.8'))),
        {steps: 38, guidance: 3.8}
    );
    for (const [steps, cfg] of [
        ['', '4'], ['20', ''], ['4.5', '4'], ['0', '4'],
        ['51', '4'], ['30', '-1'], ['30', '11'], ['NaN', '3'],
        ['30', 'Infinity']
    ]) {
        assert.equal(env.parseSamplingValues(steps, cfg), null);
    }
});

test('sampling UI is explicit for Juggernaut image generation and validated', () => {
    for (const id of ['imageSamplingField','imageSamplingSteps','imageSamplingCfg','imageSamplingHint']) {
        assert.match(html, new RegExp('id="' + id + '"'));
    }
    assert.match(html, /imageSamplingSteps" type="number" min="1" max="50"/);
    assert.match(html, /imageSamplingCfg" type="number" min="0" max="10"/);
    assert.match(css, /\.media-sampling-field\[hidden\]/);
    assert.match(source, /resolvedTarget === 'image' &&\s*selectedImageModel === 'juggernaut-xl'/);
    assert.match(source, /samplingCustom = null;\s*renderChoice\(\)/);
    assert.match(source, /selectedSampling = parsed/);
    assert.match(source, /samplingSteps\?\.addEventListener\?\.\('input', onSamplingInput\)/);
    assert.match(source, /samplingSteps\?\.removeEventListener\?\.\('input', onSamplingInput\)/);
    assert.match(source, /merged\.steps = samplingOverride\.steps/);
    assert.match(source, /merged\.guidance = samplingOverride\.guidance/);
    assert.match(source, /mediaQualityKind !== 'image' \|\| hasRagnarokSampling\(\)/);
});

test('sampling controls have paired German and English translations', () => {
    for (const key of [
        'ragnarok_sampling_heading',
        'image_steps', 'image_cfg', 'ragnarok_sampling_summary',
        'ragnarok_sampling_invalid'
    ]) {
        assert.equal(typeof de.ui[key], 'string', 'de.ui.' + key);
        assert.equal(typeof en.ui[key], 'string', 'en.ui.' + key);
    }
});
