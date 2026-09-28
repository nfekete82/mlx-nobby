import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const source = fs.readFileSync(
    'frontend/assets/chat/runtime-reliability.js',
    'utf8'
);

function harness() {
    const calls = [];
    const document = {
        readyState: 'loading',
        addEventListener() {},
        getElementById() { return null; },
        querySelector() { return null; },
        body: { appendChild() {} },
        head: { appendChild() {} }
    };
    const window = {
        location: {
            origin: 'http://127.0.0.1:8090',
            href: 'http://127.0.0.1:8090/'
        },
        MLXI18n: {
            getLanguage: () => 'de'
        },
        fetch: async (input, init) => {
            calls.push({ input, init });
            return {
                ok: true,
                status: 200,
                statusText: 'OK',
                headers: new Headers(),
                body: null
            };
        },
        addEventListener() {},
        setTimeout,
        setInterval,
        clearTimeout,
        clearInterval,
        ReadableStream
    };

    vm.runInNewContext(source, {
        window,
        document,
        URL,
        Request,
        Response,
        Headers,
        ReadableStream,
        performance,
        console,
        setTimeout,
        setInterval,
        clearTimeout,
        clearInterval
    });

    return { window, calls };
}

test('normal chat streaming is routed through the reliability gateway', () => {
    const { window } = harness();
    const reliability = window.MLXRuntimeReliability;

    assert.equal(
        reliability.isChatStreamRequest(
            '/api/chat/stream',
            { method: 'POST' }
        ),
        true
    );
    assert.equal(
        reliability.reliableInput('/api/chat/stream'),
        '/api/chat/reliable-stream'
    );
});

test('non-chat and non-POST requests are not intercepted', () => {
    const { window } = harness();
    const reliability = window.MLXRuntimeReliability;

    assert.equal(
        reliability.isChatStreamRequest(
            '/api/chat/stream',
            { method: 'GET' }
        ),
        false
    );
    assert.equal(
        reliability.isChatStreamRequest(
            '/api/mlx/audio/speech/stream',
            { method: 'POST' }
        ),
        false
    );
    assert.equal(
        reliability.isChatStreamRequest(
            '/api/mlx/chat/actions',
            { method: 'POST' }
        ),
        false
    );
});

test('common loader includes runtime reliability before normal chat use', () => {
    const common = fs.readFileSync('frontend/assets/common.js', 'utf8');
    assert.match(common, /runtime-reliability\.js/);
    assert.match(common, /loadRuntimeReliability\(\)/);
});
