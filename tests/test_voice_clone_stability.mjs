import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const voice = fs.readFileSync(
    new URL('../frontend/assets/chat/voice.js', import.meta.url),
    'utf8'
);
const streamingUi = fs.readFileSync(
    new URL('../frontend/assets/chat/voice-streaming.js', import.meta.url),
    'utf8'
);
const speechApp = fs.readFileSync(
    new URL('../speech/app.py', import.meta.url),
    'utf8'
);
const speechStreaming = fs.readFileSync(
    new URL('../speech/streaming_routes.py', import.meta.url),
    'utf8'
);
const agentProxy = fs.readFileSync(
    new URL('../agent/speech_streaming_routes.py', import.meta.url),
    'utf8'
);
const backendProxy = fs.readFileSync(
    new URL('../backend/speech_streaming_routes.py', import.meta.url),
    'utf8'
);


test('voice picker discovers local profiles through the speech service', () => {
    assert.match(agentProxy, /\/v1\/audio\/voices/);
    assert.match(agentProxy, /\/api\/mlx\/audio\/voices/);
    assert.match(backendProxy, /\/api\/mlx\/audio\/voices/);
    assert.match(voice, /nativeFetch\('\/api\/mlx\/audio\/voices'/);
    assert.match(voice, /normalizeVoiceList/);
    assert.match(voice, /getVoices:/);
});


test('reference cloning uses conservative sampling instead of library defaults', () => {
    assert.match(
        speechApp,
        /MLX_TTS_CLONE_TEMPERATURE[\s\S]*?0\.65/
    );
    assert.match(speechApp, /MLX_TTS_CLONE_TOP_K[\s\S]*?30/);
    assert.match(speechApp, /MLX_TTS_CLONE_TOP_P[\s\S]*?0\.90/);
    assert.match(speechApp, /\*\*clone_generation_options\(\)/);
    assert.match(speechStreaming, /\*\*clone_generation_options\(\)/);
});


test('clone streaming waits for more initial codec context', () => {
    assert.match(
        speechStreaming,
        /MLX_TTS_CLONE_STREAM_INTERVAL[\s\S]*?0\.80/
    );
    assert.match(
        speechStreaming,
        /stream_interval = _CLONE_STREAM_INTERVAL/
    );
});


test('streamed playback reuses exact generated PCM on normal replay', () => {
    assert.match(streamingUi, /const streamCache = new Map\(\)/);
    assert.match(streamingUi, /function rememberStream/);
    assert.match(streamingUi, /streamCache\.get\(key\)/);
    assert.match(streamingUi, /rememberStream\(session\.replayKey, session\.recordedChunks\)/);
    assert.match(streamingUi, /forceRegenerate = event\.shiftKey === true/);
    assert.match(streamingUi, /streamCache\.delete\(replayKey\(text, settings\)\)/);
});
