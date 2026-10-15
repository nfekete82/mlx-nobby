import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const render = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');
const style = fs.readFileSync('frontend/assets/chat.css', 'utf8');
const de = JSON.parse(fs.readFileSync('frontend/i18n/de.json', 'utf8'));
const en = JSON.parse(fs.readFileSync('frontend/i18n/en.json', 'utf8'));

test('news briefing renders structured provider-backed content, not raw source HTML', () => {
    assert.match(render, /function renderGroundedNewsDigest\(/);
    assert.match(render, /Array\.isArray\(message\.news_digest\.items\)/);
    assert.match(render, /brief\.textContent = String\(item\.summary\)/);
    assert.match(render, /link\.textContent = title/);
    assert.match(render, /parsed\.protocol === 'https:'/);
    assert.match(render, /!parsed\.username/);
    assert.match(render, /!parsed\.password/);
    assert.match(render, /renderGroundedNewsDigest\(answer, message\.news_digest\)/);
});
test('publisher and publication time are visually secondary', () => {
    assert.match(render, /news-briefing-item-title/);
    assert.match(render, /news-briefing-meta/);
    assert.match(render, /news-briefing-summary/);
    assert.match(style, /\.message-news-digest \.news-briefing-meta \{/);
    assert.match(style, /\.message-news-digest \.news-briefing-summary \{/);
    assert.match(style, /font-size: 11px;/);
});
test('headline count warning and evidence notice exist in German and English', () => {
    for (const key of ['news_briefing_heading', 'news_briefing_partial',
                       'news_briefing_ai_note', 'news_briefing_source_note']) {
        assert.equal(typeof de.rendering[key], 'string', key + ' de');
        assert.equal(typeof en.rendering[key], 'string', key + ' en');
        assert.ok(de.rendering[key].length > 10);
        assert.ok(en.rendering[key].length > 10);
    }
    assert.match(de.rendering.news_briefing_partial, /\{actual\}.*\{requested\}/);
    assert.match(en.rendering.news_briefing_partial, /\{actual\}.*\{requested\}/);
});
