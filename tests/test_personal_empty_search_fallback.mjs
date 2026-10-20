import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const src = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const start = src.indexOf('function shouldAnswerAfterEmptyWebSearch(');
const end = src.indexOf('\nfunction gt(', start);
assert.ok(start > -1 && end > start);
const helper = vm.runInNewContext(src.slice(start, end) + '\nshouldAnswerAfterEmptyWebSearch');

const example = 'mein chef ist so ein riesen vollidiot wir haben o2 angebote auf unserer webseite, lt. statistiken gehen die besucher drauf aber gehen schnell wieder und die meisten geben feedback dass es einfach zu teuer ist. jetzt sagt mein chef es liegt daran dass wir es nicht in jedem newsletter bewerben';
test('irrelevant empty search still answers workplace/relationship question', () => {
    assert.equal(helper(example, {data: {results: []}}), true);
    assert.equal(helper('Meine Mutter meint ich müsse helfen, das ärgert mich', {data:{results:[]}}), true);
});
test('explicit searches, weather, news and external factual questions never fabricate', () => {
    assert.equal(helper('Mein Chef sagt, suche im Internet aktuelle O2 Angebote', {data:{results:[]}}), false);
    assert.equal(helper('Mein Chef meint, recherchiere aktuelle Angebote', {data:{results:[]}}), false);
    assert.equal(helper('Mein Chef meint, finde mir Quellen dafür', {data:{results:[]}}), false);
    assert.equal(helper(example, {data:{weather_forecast:{status:'available',answer:'...'}}}), false);
    assert.equal(helper(example, {data:{news_digest:{answer:'...'}}}), false);
    assert.equal(helper('Welche O2 Angebote sind heute aktuell?', {data:{results:[]}}), false);
});
test('empty web tool recovery resumes generation instead of returning canned answer', () => {
    const branch = src.slice(src.indexOf('if (!results.length) {'), src.indexOf('const searchContext ='));
    assert.match(branch, /shouldAnswerAfterEmptyWebSearch\(prompt, toolResult\)/);
    assert.match(branch, /await generateAssistant\(session\)/);
    assert.match(branch, /web_search_no_results/);
});
