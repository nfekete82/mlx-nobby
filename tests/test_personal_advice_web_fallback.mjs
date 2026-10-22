import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const start = source.indexOf('function shouldResumeChatAfterEmptySearch(toolResult) {');
const end = source.indexOf('\nfunction gt(', start);
assert.ok(start >= 0 && end > start, 'Isolated empty-search fallback function must exist');
const shouldFallback = vm.runInNewContext(
    source.slice(start, end) + '\nshouldResumeChatAfterEmptySearch',
    {}
);

const result = (data, tool = 'web_search', status = 'completed') =>
    ({tool, status, data});

test('Only Agent-certified empty personal searches resume ordinary chat', () => {
    assert.equal(shouldFallback(result({
        empty_search_chat_fallback: true, results: []
    })), true);
    assert.equal(shouldFallback(result({
        empty_search_chat_fallback: false, results: []
    })), false);
    assert.equal(shouldFallback(result({results: []})), false);
    assert.equal(shouldFallback(result({
        empty_search_chat_fallback: true,
        results: [{title: 'source'}]
    })), false);
    assert.equal(shouldFallback(result({
        empty_search_chat_fallback: true, results: []
    }, 'image_generate')), false);
    assert.equal(shouldFallback(result({
        empty_search_chat_fallback: true, results: []
    }, 'web_search', 'failed')), false);
});

test('Weather and news safeguards outrank empty web fallback', () => {
    assert.equal(shouldFallback(result({
        empty_search_chat_fallback: true, results: [],
        weather_forecast: {status: 'location_required'}
    })), false);
    assert.equal(shouldFallback(result({
        empty_search_chat_fallback: true, results: [],
        news_digest: {answer: 'Nothing verified'}
    })), false);
});

test('Fallback continues inference before generic no-results response', () => {
    const block = source.match(/if \(!results\.length\) \{([\s\S]*?)const providerStatus/);
    assert.ok(block, 'Empty-search branch must exist');
    assert.match(block[1], /shouldResumeChatAfterEmptySearch\(toolResult\)/);
    assert.match(block[1], /await generateAssistant\(session\);/);
    assert.match(block[1], /return;/);
    assert.doesNotMatch(block[1], /userMessage\.content\s*=/,
        'Original user context should not be replaced with invented web context');
});
