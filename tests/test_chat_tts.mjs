import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const rendering = fs.readFileSync(new URL('../frontend/assets/chat/rendering.js', import.meta.url), 'utf8');
const controller = fs.readFileSync(new URL('../frontend/assets/chat/assistant-read-aloud.js', import.meta.url), 'utf8');

test('rendering exposes accessible speech controls; controller owns requests and audio', () => {
    assert.match(rendering, /mlx-message-speech-button/);
    assert.match(rendering, /mlx-message-speech-status/);
    assert.match(rendering, /'aria-live',\s*'polite'/);
    assert.doesNotMatch(rendering, /speechAudio|speechAbortController|speechRunId|splitSpeechText|\/api\/mlx\/audio\/speech/);
    assert.match(controller, /new Audio/);
    assert.match(controller, /\/api\/mlx\/audio\/speech/);
    assert.match(controller, /URL.revokeObjectURL/);
});
