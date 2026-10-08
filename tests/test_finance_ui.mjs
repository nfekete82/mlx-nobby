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
        timestamp: 1780500000, age_seconds: 2000, stale: true, delay_status: 'unknown', source: 'fixture'},
    display_fx: {target_currency: 'EUR', rates: {USD: {rate: .9, source: 'European Central Bank', date: '2026-10-07', source_url: 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'}}} };
test('quotes show exchange, currency, session, timestamp and stale data bilingually', () => {
    for (const locale of ['de', 'en']) {
        const copy = ui(locale).summary({status: 'completed', data: {kind: 'quote', ...quote}});
        assert.match(copy, /AMD/); assert.match(copy, /NASDAQ/); assert.match(copy, /USD/);
        assert.match(copy, /2026/); assert.match(copy, /33 min 20 s/);
        assert.match(copy, /111[,.]11/); assert.match(copy, /123[,.]45/);
        assert.match(copy, locale === 'de' ? /VERALTET/ : /STALE/);
        assert.match(copy, locale === 'de' ? /kein garantierter Echtzeitkurs/ : /no guaranteed live quote/);
    }
});

test('EUR display is primary and original USD stays visible', () => {
    for (const locale of ['de', 'en']) {
        const api = ui(locale);
        const shown = api.__test.money(quote, 123.45, 'USD');
        assert.match(shown, /111[,.]11/);
        assert.match(shown, /123[,.]45/);
        assert.match(shown, /€/);
        assert.match(shown, /\$/);
        assert.match(api.__test.fxLabel(quote, 'USD'), /European Central Bank/);
        assert.equal(api.__test.money(quote, 99, 'EUR').includes('('), false);
    }
});

test('history helpers filter ranges and build stable chart geometry', () => {
    const api = ui('de');
    const data = {...quote, history: {price_basis: 'close', bars: Array.from({length: 500}, (_, i) => ({
        timestamp: 1780500000 - (499 - i) * 86400,
        close: 100 + i * .2
    }))}};
    const oneYear = api.__test.historyRange(data, 365);
    assert.ok(oneYear.length >= 365 && oneYear.length <= 367);
    const geometry = api.__test.chartGeometry(oneYear);
    assert.equal(geometry.points.length, oneYear.length);
    assert.match(geometry.line, /^M /);
    assert.match(geometry.area, / Z$/);
    assert.ok(geometry.high > geometry.low);
    assert.equal(api.__test.historySeries(data).length, 500);
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
test('finance assets and native cards are wired to production chat', () => {
    const html = fs.readFileSync('frontend/chat.html', 'utf8');
    assert.match(html, /\/assets\/chat\/finance\.css\?v=20261008-finance-speed/);
    assert.ok(html.indexOf('/assets/chat/finance.js?') < html.indexOf('/assets/chat/generation.js?'));
    const generation = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
    assert.match(generation, /MLXFinance\.summary/); assert.match(generation, /MLXFinance\.failure/);
    const rendering = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');
    assert.match(rendering, /MLXFinance\?\.render/);
    assert.match(rendering, /startsWith\('finance_'\)/);
    const finance = fs.readFileSync('frontend/assets/chat/finance.js', 'utf8');
    for (const marker of ['finance-card', 'finance-metrics', 'finance-assessment', 'finance-comparison']) {
        assert.match(finance, new RegExp(marker));
    }
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

test('chat and agent cards have human finance labels in both translation catalogs', () => {
    const keys = ['finance_quote', 'finance_analyze', 'finance_compare', 'finance_portfolio_analysis',
        'finance_history', 'finance_recommendation_performance'];
    for (const language of ['de', 'en']) {
        const catalog = JSON.parse(fs.readFileSync(`frontend/i18n/${language}.json`, 'utf8'));
        for (const key of keys) assert.ok(catalog[`rendering.${key}`]);
    }
    const source = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');
    assert.match(source, /financeToolLabel\(result\.tool\)/);
    assert.match(source, /financeToolLabel\(action\)/);
});

test('unknown agent actions cannot be mistaken for finance label entries', () => {
    const source = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');
    const helper = source.slice(source.indexOf('function financeToolLabel(tool)'), source.indexOf('function renderToolCard(message)'));
    const window = {};
    vm.runInNewContext(helper + '\nwindow.label = financeToolLabel;', {window, rt: (key, fallback) => fallback});
    assert.equal(window.label('finance_quote'), 'Stock quote');
    for (const action of ['constructor', '__proto__', 'final', 'unknown']) assert.equal(window.label(action), null);
});
