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
const controller = fs.readFileSync(
    new URL('../frontend/assets/chat/assistant-read-aloud.js', import.meta.url),
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

test('canonical TTS controller animates a spinner while retaining cancellation', () => {
    assert.match(controller, /generating: '<path d="M12 3a9/);
    assert.match(controller, /setIcon\(state, 'generating'\)/);
    assert.match(controller, /button\.disabled = false/);
    assert.match(controller, /mlx-message-speech-button\.is-generating svg/);
    assert.match(controller, /animation: mlx-assistant-speech-spin \.8s linear infinite/);
    assert.match(controller, /cursor: pointer/);
});

test('TTS loading indicator respects reduced motion', () => {
    assert.match(controller, /prefers-reduced-motion: reduce/);
    assert.match(controller, /animation: none/);
});
