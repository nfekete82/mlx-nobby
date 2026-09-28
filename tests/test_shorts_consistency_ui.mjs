import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const source = fs.readFileSync('frontend/assets/chat/shorts-consistency-ui.js', 'utf8');

function harness() {
    const listeners = [];
    const document = {
        readyState: 'loading',
        addEventListener: (name, fn) => listeners.push([name, fn]),
        querySelector: () => null,
        querySelectorAll: () => [],
        createElement: () => ({
            dataset: {},
            classList: { add() {} },
            append() {},
            appendChild() {},
            addEventListener() {},
            set textContent(_value) {},
        }),
        head: { appendChild() {} },
        body: {},
    };
    const window = {
        MLXShortsStudio: { getActiveJob: () => null },
    };
    function MutationObserver() {
        this.observe = () => {};
    }
    vm.runInNewContext(source, { window, document, MutationObserver, console });
    return window.MLXShortsConsistency;
}

function job() {
    return {
        project: {
            consistency_mode: true,
            character_consistency: true,
            style_consistency: true,
            style_strength: 0.8,
        },
        keyframe_results: [
            {
                scene_id: 'scene-1',
                status: 'completed',
                image_id: '1700000000-abcdef123456',
                path: '/images/one.png',
            },
        ],
    };
}

test('unchanged consistency settings produce no revision fields', () => {
    const api = harness();
    assert.deepEqual(
        api.buildSettingsPayload(job(), {
            consistency_mode: true,
            character_consistency: true,
            style_consistency: true,
            style_strength: 0.8,
        }),
        {}
    );
});

test('changed strength and mode are sent explicitly', () => {
    const api = harness();
    const payload = api.buildSettingsPayload(job(), {
        consistency_mode: false,
        character_consistency: true,
        style_consistency: true,
        style_strength: 0.55,
    });
    assert.equal(payload.consistency_mode, false);
    assert.equal(payload.style_strength, 0.55);
});

test('forced keyframe regeneration has its own revision flag', () => {
    const api = harness();
    const payload = api.buildSettingsPayload(job(), {
        consistency_mode: true,
        character_consistency: true,
        style_consistency: true,
        style_strength: 0.8,
    }, true);
    assert.deepEqual(payload, { force_regenerate_keyframe: true });
});

test('keyframe lookup returns only completed selected scene artifacts', () => {
    const api = harness();
    assert.equal(api.keyframeFor(job(), 'scene-1').image_id, '1700000000-abcdef123456');
    assert.equal(api.keyframeFor(job(), 'scene-2'), null);
});
