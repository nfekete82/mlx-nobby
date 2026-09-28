import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const historySource = fs.readFileSync(
    new URL('../frontend/assets/chat/shorts-history.js', import.meta.url),
    'utf8'
);
const commonSource = fs.readFileSync(
    new URL('../frontend/assets/common.js', import.meta.url),
    'utf8'
);
const translations = JSON.parse(fs.readFileSync(
    new URL('../frontend/i18n/shorts-studio.json', import.meta.url),
    'utf8'
));


test('Shorts history loads grouped project endpoint', () => {
    assert.match(historySource, /\/api\/mlx\/shorts-jobs\?limit=100/);
    assert.match(historySource, /projects = Array\.isArray\(payload\.projects\)/);
});


test('Shorts history reopens a persisted job in Shorts Studio', () => {
    assert.match(
        historySource,
        /\/api\/mlx\/shorts-jobs\/\$\{encodeURIComponent\(project\.id\)\}/
    );
    assert.match(historySource, /MLXShortsStudio\?\.getActiveJob/);
    assert.match(historySource, /MLXShortsStudio\?\.open/);
});


test('Shorts history exposes project filters and localized new-short entry', () => {
    for (const filter of ['all', 'active', 'completed', 'failed']) {
        assert.match(historySource, new RegExp(`'${filter}'`));
    }
    assert.match(historySource, /Create a 20-second Short about/);
    assert.equal(
        translations.de.history_prompt,
        'Erstelle ein 20-sekündiges Short über '
    );
    assert.equal(
        translations.en.history_prompt,
        'Create a 20-second Short about '
    );
});


test('Shorts history uses shared Shorts Studio translations', () => {
    assert.match(historySource, /\/i18n\/shorts-studio\.json/);
    assert.equal(translations.de.history_open, 'Öffnen');
    assert.equal(translations.en.history_open, 'Open');
});


test('common loader installs the Shorts history browser', () => {
    assert.match(commonSource, /loadShortsHistory/);
    assert.match(commonSource, /\/assets\/chat\/shorts-history\.js/);
    assert.match(commonSource, /mlx-shorts-history/);
});
