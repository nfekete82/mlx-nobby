import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const rendering = fs.readFileSync(
    new URL(
        '../frontend/assets/chat/rendering.js',
        import.meta.url
    ),
    'utf8'
);

test('assistant messages expose local Serena TTS', () => {
    assert.match(
        rendering,
        /mlx-message-speech-button/
    );

    assert.match(
        rendering,
        /\/api\/mlx\/audio\/speech/
    );

    assert.match(
        rendering,
        /voice:\s*'Serena'/
    );

    assert.match(
        rendering,
        /language:\s*'de'/
    );

    assert.match(
        rendering,
        /new Audio\(speechUrl\)/
    );

    assert.match(
        rendering,
        /URL\.revokeObjectURL/
    );
});

console.log(
    'Chat TTS button, Serena routing, playback and cleanup passed.'
);

test('long speech is chunked and exposes progress', () => {
    assert.match(
        rendering,
        /maxChars = 1500/
    );

    assert.match(
        rendering,
        /splitSpeechText/
    );

    assert.match(
        rendering,
        /speech_generating_progress/
    );

    assert.match(
        rendering,
        /current.*total/s
    );

    assert.match(
        rendering,
        /for \(\s*let index = 0;/
    );

    assert.match(
        rendering,
        /await playSpeechBlob\(\s*blob,\s*runId\s*\)/
    );
});


test('speech progress uses inline status instead of alert', () => {
    assert.match(
        rendering,
        /mlx-message-speech-status/
    );

    assert.match(
        rendering,
        /speech_progress/
    );

    assert.match(
        rendering,
        /speech_playing/
    );

    assert.match(
        rendering,
        /speech_failed_inline/
    );

    assert.doesNotMatch(
        rendering,
        /alert\(\s*rt\(\s*'speech_failed'/
    );
});


test('speech stop cancels the active chunk run', () => {
    assert.match(
        rendering,
        /let speechRunId = 0/
    );

    assert.match(
        rendering,
        /const cancelSpeechPlayback = \(\) =>/
    );

    assert.match(
        rendering,
        /speechRunId \+= 1/
    );

    assert.match(
        rendering,
        /cancelSpeechPlayback\(\)/
    );

    assert.match(
        rendering,
        /const runId = \+\+speechRunId/
    );

    assert.match(
        rendering,
        /runId !== speechRunId/
    );

    assert.match(
        rendering,
        /const completed =\s*await playSpeechBlob\(\s*blob,\s*runId\s*\)/
    );

    assert.match(
        rendering,
        /!completed \|\|\s*runId !== speechRunId/
    );
});


test('speech stop aborts active TTS request', () => {
    assert.match(
        rendering,
        /let speechAbortController = null/
    );

    assert.match(
        rendering,
        /speechAbortController\.abort\(\)/
    );

    assert.match(
        rendering,
        /new AbortController\(\)/
    );

    assert.match(
        rendering,
        /signal:\s*speechAbortController\.signal/
    );

    assert.match(
        rendering,
        /error\?\.name === 'AbortError'/
    );
});
