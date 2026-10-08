import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/assets/chat/help.js', 'utf8');
// Capture the private data factory in the test VM without adding a runtime API.
function topics(locale) {
    const window = { MLXI18n: { getLanguage: () => locale } };
    vm.runInNewContext(source.replace('function injectStyles()',
        'window.testTopics = topicData; function injectStyles()'), {
        window, document: { readyState: 'loading', addEventListener() {} }
    });
    return window.testTopics();
}

const required = ['getting-started', 'images', 'video', 'shorts', 'voice', 'agent',
    'knowledge', 'finance', 'models', 'memory', 'automations', 'diagnostics', 'api-integrations',
    'troubleshooting'];

test('help topics have unique stable IDs and complete DE/EN sections', () => {
    const de = topics('de'), en = topics('en');
    assert.deepEqual(Array.from(de, x => x.id), Array.from(en, x => x.id));
    for (const data of [de, en]) {
        const ids = data.map(x => x.id);
        assert.equal(new Set(ids).size, ids.length);
        for (const id of required) assert.ok(ids.includes(id), id);
        for (const topic of data) {
            assert.ok(topic.title.trim() && topic.summary.trim(), topic.id);
            assert.ok(topic.sections.length, topic.id);
            for (const section of topic.sections) {
                assert.ok(section.title.trim() && section.body.trim(), topic.id);
                for (const step of section.steps || []) assert.ok(step.trim());
            }
        }
    }
    for (let i = 0; i < de.length; i++) {
        assert.notEqual(de[i].title, en[i].title, de[i].id);
        assert.equal(de[i].sections.length, en[i].sections.length);
        de[i].sections.forEach((section, j) => {
            assert.notEqual(section.body, en[i].sections[j].body);
            assert.equal(section.steps?.length, en[i].sections[j].steps?.length);
            assert.equal(section.code, en[i].sections[j].code);
        });
    }
});

test('help reflects draft/render, local API and supported commands', () => {
    const cli = fs.readFileSync('scripts/mlx', 'utf8');
    const gateway = fs.readFileSync('backend/openai_gateway.py', 'utf8');
    for (const locale of ['de', 'en']) {
        const data = topics(locale);
        const text = id => JSON.stringify(data.find(x => x.id === id));
        const shorts = text('shorts');
        assert.match(shorts, /Draft|draft/);
        assert.match(shorts, /Render Short/);
        assert.match(shorts, locale === 'de' ? /keine Bilder oder Videos/ : /No images or videos/);
        assert.doesNotMatch(shorts, /plans and produces the scenes automatically|plant und produziert die Szenen automatisch|What happens automatically|Was automatisch passiert/);
        const api = text('api-integrations');
        assert.match(api, /http:\/\/127\.0\.0\.1:8090\/v1/);
        assert.match(api, /\/v1\/models/);
        assert.match(api, /\/v1\/chat\/completions/);
        assert.match(api, /stateless/);
        assert.match(api, /Loopback|loopback/);
        assert.match(api, locale === 'de' ? /Keine Authentifizierung/ : /No authentication/);
        assert.match(api, /Cline/);
        for (const role of ['coding', 'chat', 'agent']) {
            assert.match(api, new RegExp(`mlx-nobby/${role}`));
            assert.ok(gateway.includes(`"${role}"`));
        }
        const commands = data.find(x => x.id === 'troubleshooting').sections
            .flatMap(x => (x.code || '').split('\n'));
        for (const command of commands) {
            if (command.startsWith('mlx ')) {
                const name = command.slice(4);
                assert.ok(cli.includes(`    ${name})`), command);
            } else if (command.startsWith('./scripts/')) {
                assert.ok(fs.existsSync(command.slice(2)), command);
            }
        }
        assert.match(text('images'), /1–6/);
    }
});

test('finance help explains verified sources, confidence, markets and tracking in both languages', () => {
    for (const locale of ['de', 'en']) {
        const topic = topics(locale).find(t => t.id === 'finance');
        const copy = JSON.stringify(topic);
        for (const pattern of [/Yahoo Finance/, /Western Digital/, /NASDAQ\/USD/, /Stuttgart\/Xetra\/EUR/, /insufficient data/,
            /Confidence/, /70%/, /85–100/, /Strong Buy/, /90/, /docs\/FINANCE\.md/]) assert.match(copy, pattern);
        assert.match(copy, locale === 'de' ? /Finance-Karten/ : /Finance cards/);
        assert.equal(topic.examples.length, 5);
        assert.match(copy, locale === 'de' ? /keine erfundenen Werte/ : /never create invented values/);
    }
    const de = topics('de').find(t => t.id === 'finance');
    for (const prompt of ['Wie steht AMD gerade?', 'Analysiere AMD fundamental und technisch.',
        'Vergleiche AMD und NVIDIA.', 'Welche Risiken siehst du bei AMD?']) assert.ok(de.examples.includes(prompt));
});
