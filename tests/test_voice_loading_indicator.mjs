import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const common = fs.readFileSync(
    new URL('../frontend/assets/common.js', import.meta.url),
    'utf8'
);
const loading = fs.readFileSync(
    new URL('../frontend/assets/chat/voice-loading.js', import.meta.url),
    'utf8'
);
const rendering = fs.readFileSync(
    new URL('../frontend/assets/chat/rendering.js', import.meta.url),
    'utf8'
);

test('chat loads the TTS loading indicator with voice controls', () => {
    assert.match(common, /voice-loading\.js/);
    assert.match(common, /mlx-voice-loading/);
    assert.ok(
        common.indexOf('voice.js') < common.indexOf('voice-loading.js'),
        'voice loading styles should load after the base voice controls'
    );
});

test('TTS loading indicator animates the existing generating icon', () => {
    assert.match(rendering, /const loadingIcon/);
    assert.match(rendering, /speech\.disabled = true/);
    assert.match(rendering, /speech\.innerHTML = loadingIcon/);
    assert.match(loading, /mlx-message-speech-button:disabled svg/);
    assert.match(loading, /mlx-speech-loading-spin/);
    assert.match(loading, /animation: mlx-speech-loading-spin \.8s linear infinite/);
    assert.match(loading, /cursor: progress/);
});

test('TTS loading indicator respects reduced motion', () => {
    assert.match(loading, /prefers-reduced-motion: reduce/);
    assert.match(loading, /animation: none/);
});
