import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const common = fs.readFileSync(
    new URL('../frontend/assets/common.js', import.meta.url),
    'utf8'
);
const voice = fs.readFileSync(
    new URL('../frontend/assets/chat/voice.js', import.meta.url),
    'utf8'
);

test('chat loads voice controls', () => {
    assert.match(common, /chat\/voice\.js/);
    assert.match(common, /loadChatVoiceControls/);
});

test('voice popover exposes Pervin and Serena', () => {
    assert.match(voice, /voice:\s*'Pervin'/);
    assert.match(voice, /id:\s*'Pervin'/);
    assert.match(voice, /id:\s*'Serena'/);
    assert.match(voice, /mlxVoicePopover/);
    assert.match(voice, /Antworten automatisch vorlesen/);
});

test('speech requests inherit selected voice and speed', () => {
    assert.match(voice, /body\.voice\s*=\s*settings\.voice/);
    assert.match(voice, /body\.speed\s*=\s*settings\.speed/);
    assert.match(voice, /\/api\/mlx\/audio\/speech/);
});
