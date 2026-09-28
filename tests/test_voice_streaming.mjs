import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const streaming = fs.readFileSync(
    new URL('../frontend/assets/chat/voice-streaming.js', import.meta.url),
    'utf8'
);
const common = fs.readFileSync(
    new URL('../frontend/assets/common.js', import.meta.url),
    'utf8'
);

test('experimental voice streaming remains available after voice settings', () => {
    assert.match(common, /voice-streaming\.js/);
    assert.match(common, /mlx-voice-streaming/);
    assert.ok(
        common.indexOf('voice.js') < common.indexOf('voice-streaming.js'),
        'voice settings must load before the streaming enhancer'
    );
});

test('browser defaults to stable buffered TTS unless streaming is explicitly enabled', () => {
    assert.match(common, /experimentalVoiceStreamingEnabled/);
    assert.match(common, /mlx-nobby-voice-streaming/);
    assert.match(common, /getItem\('mlx-nobby-voice-streaming'\) === '1'/);
    assert.match(common, /if \(experimentalVoiceStreamingEnabled\(\)\)/);
});

test('voice streaming uses NDJSON and Web Audio scheduling', () => {
    assert.match(streaming, /\/api\/mlx\/audio\/speech\/stream/);
    assert.match(streaming, /AudioContext/);
    assert.match(streaming, /response\.body\.getReader\(\)/);
    assert.match(streaming, /new Float32Array/);
    assert.match(streaming, /createBuffer\(/);
    assert.match(streaming, /createBufferSource\(/);
    assert.match(streaming, /source\.start\(startAt\)/);
});

test('streaming only intercepts 1.0x and preserves buffered fallback', () => {
    assert.match(streaming, /settings\.speed/);
    assert.match(streaming, /1\.0/);
    assert.match(streaming, /BUFFERED_ENDPOINT = '\/api\/mlx\/audio\/speech'/);
    assert.match(streaming, /playBufferedFallback/);
    assert.match(streaming, /Streaming failed, using MP3 fallback/);
});

test('streaming interception supports assistant, user and composer speech', () => {
    assert.match(streaming, /mlx-message-speech-button/);
    assert.match(streaming, /mlx-user-speech-button/);
    assert.match(streaming, /mlx-voice-preview/);
    assert.match(streaming, /stopImmediatePropagation\(\)/);
    assert.match(streaming, /addEventListener\('click',[\s\S]*true\)/);
});

test('streaming playback supports pause, resume and cancellation', () => {
    assert.match(streaming, /context\.suspend\(\)/);
    assert.match(streaming, /context\.resume\(\)/);
    assert.match(streaming, /controller\?\.abort\(\)/);
    assert.match(streaming, /source\.stop\(\)/);
    assert.match(streaming, /mlx:voice-settings-changed/);
});