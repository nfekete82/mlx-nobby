import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
function ui(locale) {
    const window = { MLXI18n: { getLanguage: () => locale } };
    vm.runInNewContext(fs.readFileSync('frontend/assets/chat/finance.js', 'utf8'), {window, Intl, Date});
    return window.MLXFinance;
}
const quote = { instrument: {symbol: 'AMD', name: 'Advanced Micro Devices', exchange: 'NASDAQ', currency: 'USD'},
    quote: {price: 123.45, symbol: 'AMD', exchange: 'NASDAQ', currency: 'USD', session: 'regular',
        timestamp: 1780500000, age_seconds: 2000, stale: true, delay_status: 'unknown', source: 'fixture'} };
test('quotes show exchange, currency, session, timestamp and stale data bilingually', () => {
    for (const locale of ['de', 'en']) {
        const copy = ui(locale).summary({status: 'completed', data: {kind: 'quote', ...quote}});
        assert.match(copy, /AMD/); assert.match(copy, /NASDAQ/); assert.match(copy, /USD/);
        assert.match(copy, /2026-/); assert.match(copy, /2[.,]000 s/);
        assert.match(copy, locale === 'de' ? /VERALTET/ : /STALE/);
        assert.match(copy, locale === 'de' ? /kein garantierter Echtzeitkurs/ : /no guaranteed live quote/);
    }
});
test('analysis preserves insufficient data rather than rendering a rating', () => {
    for (const locale of ['de', 'en']) {
        const copy = ui(locale).summary({status: 'completed', data: {kind: 'analysis', ...quote,
            assessment: {score: null, confidence: .2, reasons: ['stale_quote']}}});
        assert.match(copy, /[Ii]nsufficient data/); assert.doesNotMatch(copy, /Strong Buy|NaN|undefined/);
        assert.match(copy, locale === 'de' ? /Gewinnwahrscheinlichkeit/ : /profit probability/);
    }
});
test('external fields cannot create HTML or Markdown instructions', () => {
    const copy = ui('en').summary({status: 'completed', data: {kind: 'quote', ...quote,
        instrument: {symbol: 'AMD', name: '<img src=x onerror=alert(1)>[click](javascript:evil)'}}});
    assert.doesNotMatch(copy, /<img|\[click\]/);
});
test('portfolio never renders missing weights as zero and errors are localized', () => {
    for (const locale of ['de', 'en']) {
        const copy = ui(locale).summary({status: 'completed', data: {kind: 'portfolio', status: 'currency_conversion_required',
            positions: [{instrument: quote.instrument, quantity: 10, value: 100}]}});
        assert.match(copy, locale === 'de' ? /Verschiedene Währungen/ : /Mixed currencies/);
        assert.doesNotMatch(copy, /NaN|undefined/);
        assert.match(ui(locale).failure({data: {code: 'provider_identity_conflict'}}), locale === 'de' ? /Widersprüchliche/ : /Conflicting/);
    }
});
test('finance assets and direct tool output are wired to production chat', () => {
    const html = fs.readFileSync('frontend/chat.html', 'utf8');
    assert.ok(html.indexOf('/assets/chat/finance.js?') < html.indexOf('/assets/chat/generation.js?'));
    const generation = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
    assert.match(generation, /MLXFinance\.summary/); assert.match(generation, /MLXFinance\.failure/);
});

test('tracking distinguishes saved-price change from the dated daily benchmark window', () => {
    for (const locale of ['de', 'en']) {
        const copy = ui(locale).summary({status: 'completed', data: {kind: 'tracking', items: [{
            symbol: 'AMD', return: -.282, history_return: .38, history_alpha: .1, benchmark_return: .28,
            quote_from: 1780500000, as_of: 1789500000, history_from: 1780400000, history_to: 1789400000,
            history_basis: 'adjusted_close', max_drawdown: -.1, drawdown_complete: false
        }], statistics: {average_return: -.282}}});
        assert.match(copy, /-28[.,]2%/);
        assert.match(copy, locale === 'de' ? /seit Empfehlung \(unbereinigt\)/ : /since recommendation \(unadjusted\)/);
        assert.match(copy, locale === 'de' ? /Separates Tageskursfenster/ : /Separate daily-close window/);
        assert.match(copy, locale === 'de' ? /keine Gesamtrendite/ : /not total returns/);
    }
});
