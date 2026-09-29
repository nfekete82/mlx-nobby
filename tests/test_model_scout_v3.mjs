import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/model-scout-v3.js', import.meta.url),
    'utf8',
);

const storage = new Map();
const localStorage = {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, String(value)); },
};

const window = {};
window.window = window;

class MutationObserverStub {
    observe() {}
    disconnect() {}
}

const document = {
    readyState: 'loading',
    documentElement: {},
    addEventListener() {},
    querySelector() { return null; },
};

const context = {
    window,
    document,
    navigator: { language: 'en-US' },
    localStorage,
    MutationObserver: MutationObserverStub,
    requestAnimationFrame() {},
    console,
    Intl,
    Date,
    Array,
    String,
    Number,
    Object,
    Map,
    Set,
    Promise,
    Error,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/model-scout-v3.js',
});

const api = window.MLXModelScoutV3;
assert.equal(typeof api?.sortCandidates, 'function');
assert.equal(typeof api?.latestBenchmarkFor, 'function');
assert.equal(typeof api?.preflightCandidate, 'function');

const candidates = [
    {
        id: 'mlx-community/A-4bit',
        installed: true,
        installed_alias: 'a',
        benchmark_ready: true,
        memory_fit: 'excellent',
        estimated_memory_gb: 20,
        discovery_score: 71,
        downloads: 200,
        last_modified: '2026-09-20T10:00:00Z',
        license: 'apache-2.0',
    },
    {
        id: 'mlx-community/B-4bit',
        installed: true,
        installed_alias: 'b',
        benchmark_ready: true,
        memory_fit: 'good',
        estimated_memory_gb: 14,
        discovery_score: 88,
        downloads: 100,
        last_modified: '2026-09-29T10:00:00Z',
        license: 'mit',
    },
];

const history = [
    {
        candidate_repo: 'mlx-community/A-4bit',
        candidate_alias: 'a',
        finished_at: '2026-09-29T18:00:00Z',
        candidate: {
            quality: { score: 87.5 },
            performance: { generation_tps: 42 },
        },
        comparison: { signal: 'promising' },
    },
    {
        candidate_repo: 'mlx-community/B-4bit',
        candidate_alias: 'b',
        finished_at: '2026-09-29T17:00:00Z',
        candidate: {
            quality: { score: 75 },
            performance: { generation_tps: 52 },
        },
        comparison: { signal: 'mixed' },
    },
];

assert.deepEqual(
    Array.from(api.sortCandidates(candidates, 'score', history), item => item.id),
    ['mlx-community/B-4bit', 'mlx-community/A-4bit'],
);
assert.deepEqual(
    Array.from(api.sortCandidates(candidates, 'newest', history), item => item.id),
    ['mlx-community/B-4bit', 'mlx-community/A-4bit'],
);
assert.deepEqual(
    Array.from(api.sortCandidates(candidates, 'downloads', history), item => item.id),
    ['mlx-community/A-4bit', 'mlx-community/B-4bit'],
);
assert.deepEqual(
    Array.from(api.sortCandidates(candidates, 'memory', history), item => item.id),
    ['mlx-community/B-4bit', 'mlx-community/A-4bit'],
);
assert.deepEqual(
    Array.from(api.sortCandidates(candidates, 'quality', history), item => item.id),
    ['mlx-community/A-4bit', 'mlx-community/B-4bit'],
);
assert.deepEqual(
    Array.from(api.sortCandidates(candidates, 'speed', history), item => item.id),
    ['mlx-community/B-4bit', 'mlx-community/A-4bit'],
);

assert.equal(api.latestBenchmarkFor(candidates[0], history), history[0]);
assert.equal(api.latestBenchmarkFor({ id: 'missing/model' }, history), null);

const good = api.preflightCandidate(candidates[0], history[0]);
assert.equal(good.ok, true);
assert.deepEqual(Array.from(good.blockers), []);
assert.deepEqual(Array.from(good.warnings), []);

const missingBenchmark = api.preflightCandidate(candidates[0], null);
assert.equal(missingBenchmark.ok, false);
assert.equal(Array.from(missingBenchmark.blockers).includes('benchmark'), true);

const risky = api.preflightCandidate({
    ...candidates[0],
    memory_fit: 'risky',
}, history[0]);
assert.equal(risky.ok, false);
assert.equal(Array.from(risky.blockers).includes('memory'), true);

const missingLicense = api.preflightCandidate({
    ...candidates[0],
    license: null,
}, history[0]);
assert.equal(missingLicense.ok, true);
assert.equal(Array.from(missingLicense.warnings).includes('license'), true);

const regression = api.preflightCandidate(candidates[0], {
    ...history[0],
    comparison: { signal: 'quality_regression' },
});
assert.equal(regression.ok, true);
assert.equal(Array.from(regression.warnings).includes('quality_regression'), true);

console.log('Model Scout v3 helpers passed.');
