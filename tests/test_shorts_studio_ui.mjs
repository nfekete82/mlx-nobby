import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const source = fs.readFileSync('frontend/assets/chat/shorts-studio.js', 'utf8');

function harness(settings = { voice: 'Pervin', speed: 1.1 }) {
    const calls = [];
    const window = {
        location: { origin: 'http://127.0.0.1:8090' },
        MLXVoice: { getSettings: () => ({ ...settings }) },
        fetch: async (input, init) => {
            calls.push({ input, init });
            return { ok: true };
        }
    };
    vm.runInNewContext(source, { window, URL, console });
    return { window, calls };
}

test('Shorts requests inherit the selected chat voice without changing the visible message', async () => {
    const { window, calls } = harness();
    const visiblePrompt = 'Erstelle mir ein 20-sekündiges YouTube Short über Berlin 2036';

    await window.fetch('/api/mlx/chat/actions', {
        method: 'POST',
        body: JSON.stringify({ prompt: visiblePrompt, chat_id: 'chat-one' })
    });

    assert.equal(calls.length, 1);
    const payload = JSON.parse(calls[0].init.body);
    assert.match(payload.prompt, /voice=Pervin/);
    assert.match(payload.prompt, /voice_speed=1\.1/);
    assert.equal(payload.chat_id, 'chat-one');
    assert.equal(visiblePrompt, 'Erstelle mir ein 20-sekündiges YouTube Short über Berlin 2036');
});

test('Explicit voice instructions in the prompt take precedence over UI settings', async () => {
    const { window, calls } = harness({ voice: 'Pervin', speed: 1.1 });
    const prompt = 'Erstelle ein YouTube Short und nutze die Stimme Serena';

    await window.fetch('/api/mlx/chat/actions', {
        method: 'POST',
        body: JSON.stringify({ prompt })
    });

    const payload = JSON.parse(calls[0].init.body);
    assert.equal(payload.prompt, prompt);
});

test('Normal chat action requests are not modified', async () => {
    const { window, calls } = harness();
    const prompt = 'Erstelle ein Bild von Berlin';

    await window.fetch('/api/mlx/chat/actions', {
        method: 'POST',
        body: JSON.stringify({ prompt })
    });

    const payload = JSON.parse(calls[0].init.body);
    assert.equal(payload.prompt, prompt);
});
