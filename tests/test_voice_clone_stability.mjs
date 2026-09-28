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
    assert.match(voice, /setVoice,/);
});


test('reference cloning uses stable per-voice sampling profiles', () => {
    assert.match(speechApp, /VOICE_QUALITY_PRESETS/);
    assert.match(speechApp, /"stable"[\s\S]*?0\.45/);
    assert.match(speechApp, /"natural"[\s\S]*?TTS_CLONE_TEMPERATURE/);
    assert.match(speechApp, /"expressive"[\s\S]*?0\.85/);
    assert.match(speechApp, /\*\*clone_generation_options\(request\.voice\)/);
    assert.match(speechStreaming, /\*\*clone_generation_options\(request\.voice\)/);
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


test('streamed playback terminates on protocol done and recovers stalled readers', () => {
    assert.match(streamingUi, /FIRST_AUDIO_TIMEOUT_MS = 60_000/);
    assert.match(streamingUi, /STREAM_IDLE_TIMEOUT_MS = 20_000/);
    assert.match(streamingUi, /function readStreamChunk/);
    assert.match(streamingUi, /error\.name = 'StreamStallError'/);
    assert.match(streamingUi, /event\.type === 'done'/);
    assert.match(streamingUi, /await reader\.cancel\(\)/);
    assert.match(
        streamingUi,
        /error\?\.name === 'StreamStallError' && session\.firstAudio/
    );
});
