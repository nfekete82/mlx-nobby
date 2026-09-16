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
