import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const js = fs.readFileSync(
    new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8'
);
const begin = js.indexOf('function chartInstructionForTurn(messages) {');
const end = js.indexOf('\n(function () {', begin);
assert.ok(begin >= 0 && end > begin, 'chart eligibility helper exists');

function instruction(messages, chartsEnabled = true) {
    const context = vm.createContext({
        window: {MLXCharts: chartsEnabled ? {} : undefined},
    });
    vm.runInContext(js.slice(begin, end), context);
    return context.chartInstructionForTurn(messages);
}

const text = content => [{role: 'user', content}];
const vision = question => [{role: 'user', content: [
    {type: 'text', text: question},
    {type: 'image_url', image_url: {url: 'data:image/png;base64,AAAA'}},
]}];

test('photo descriptions never solicit fabricated nobby-chart percentages', () => {
    const hint = instruction(vision('Beschreibe das Foto ausführlich.'));
    assert.match(hint, /do not invent focus percentages/i);
    assert.match(hint, /do not.*nobby-chart/i);
    assert.doesNotMatch(hint, /fenced nobby-chart JSON block/i);
});

test('ordinary chat and numeric comparisons do not solicit charts', () => {
    assert.equal(instruction(text('Was ist auf dem Bild zu erkennen?')), '');
    assert.equal(instruction(text('Vergleiche Umsatz 2024 100 und 2025 140')), '');
    assert.equal(instruction(text('Warum zeigt Nobby ein Diagramm?')), '');
    assert.equal(instruction(text('Zeige kein Diagramm für diese Werte.')), '');
    assert.equal(instruction(text('Draw no chart, just explain.')), '');
    assert.equal(instruction(text('Zeige ein Diagramm.'),
        false), '');
});

test('explicit chart prompts with numeric data can still request valid charts', () => {
    assert.match(
        instruction(text('Erstelle ein Diagramm: Januar 100, Februar 120')),
        /ONE fenced nobby-chart JSON block/
    );
    assert.match(
        instruction(text('Draw a chart comparing 2025 and 2026')),
        /Only use supplied or verified numeric data/
    );
});

test('the visible Enhance message is generic while preset stays in the payload', () => {
    assert.match(js, /gt\('image_upscale_request', 'Enhance image'\)/);
    assert.doesNotMatch(js, /'Enhance image · \{preset\}'/);
    assert.match(js, /image_options: \{ preset: option\.preset \}/);
    assert.match(js, /chartInstructionForTurn\(apiMessages\)/);
});
