import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';


const source = fs.readFileSync(
    new URL('../frontend/assets/chat/rendering.js', import.meta.url),
    'utf8',
);
const chatSource = fs.readFileSync(
    new URL('../frontend/assets/chat.js', import.meta.url),
    'utf8',
);
const html = fs.readFileSync(
    new URL('../frontend/chat.html', import.meta.url),
    'utf8',
);
const catalogs = {
    en: JSON.parse(fs.readFileSync(new URL('../frontend/i18n/en.json', import.meta.url))),
    de: JSON.parse(fs.readFileSync(new URL('../frontend/i18n/de.json', import.meta.url))),
};
let language = 'en';
const listeners = new Map();

function translation(key, fallback = '') {
    const value = String(key).split('.').reduce(
        (current, part) => current?.[part],
        catalogs[language],
    );
    return typeof value === 'string' ? value : fallback;
}

class Element {
    constructor(tag = '') {
        this.tag = tag;
        this.children = [];
        this.className = '';
        this.textContent = '';
        this.listeners = {};
        this.classList = {
            add: (...names) => {
                this.className = [this.className, ...names].filter(Boolean).join(' ');
            },
        };
    }
    appendChild(child) { this.children.push(child); return child; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
}

function allText(element) {
    return [
        element.textContent,
        ...element.children.flatMap(child => allText(child)),
    ].filter(Boolean);
}

const document = {
    getElementById() { return new Element(); },
    createElement(tag) { return new Element(tag); },
    addEventListener(name, callback) { listeners.set(name, callback); },
};
const window = {
    MLXI18n: { t: translation },
};
window.window = window;

vm.runInNewContext(source, { document, window, console }, {
    filename: 'frontend/assets/chat/rendering.js',
});

const evidence = window.MLXChatRendering.__test;
assert.equal(
    evidence.batchFailureDetail({
        status: 'failed',
        error: 'JSON-Datei ist syntaktisch ungültig'
    }),
    'JSON-Datei ist syntaktisch ungültig'
);
assert.equal(
    evidence.batchFailureDetail({
        status: 'completed',
        error: 'stale error'
    }),
    ''
);
assert.equal(
    evidence.batchFailureDetail({
        status: 'failed',
        error: 'Konkreter Fehler\nTraceback (most recent call last):\nsecret internals'
    }),
    'Konkreter Fehler'
);

const passed = {
    patch_id: 'aaaaaaaaaaaaaaaa',
    test_status: 'passed',
    checks_run: 2,
    passed: true,
    results: [
        { status: 'passed', path: 'app.js' },
        { status: 'passed', test_command: 0 },
    ],
};
assert.equal(evidence.codeTestEvidence(passed).status, 'passed');
assert.equal(evidence.codeTestEvidence(passed).checksRun, 2);
assert.equal(
    evidence.codeTestEvidenceLabel(passed),
    'Tests passed · 2 checks run',
);
assert.deepEqual(
    allText(evidence.renderCodeTestEvidence(passed)),
    ['Tests passed · 2 checks run', 'app.js', 'Passed', 'Check 2', 'Passed'],
);

const failed = {
    test_status: 'failed',
    checks_run: 2,
    passed: false,
    results: [
        { status: 'passed', path: 'app.js' },
        { status: 'failed', test_command: 0, output: 'assertion failed' },
    ],
};
assert.equal(evidence.codeTestEvidence(failed).status, 'failed');
assert.equal(evidence.codeTestEvidence(failed).failedCount, 1);
assert.equal(
    evidence.codeTestEvidenceLabel(failed),
    'Tests failed · 1 of 2 checks failed',
);
assert.ok(
    allText(evidence.renderCodeTestEvidence(failed)).includes('assertion failed')
);

const noChecks = {
    test_status: 'no_checks',
    checks_run: 0,
    passed: false,
    results: [{ status: 'skipped', path: 'index.html' }],
};
assert.equal(evidence.codeTestEvidence(noChecks).status, 'no_checks');
assert.equal(
    evidence.codeTestEvidenceLabel(noChecks),
    'Not tested · No suitable test is configured for this workspace.',
);
const noChecksPanel = evidence.renderCodeTestEvidence(noChecks);
assert.ok(allText(noChecksPanel).includes(
    'No suitable test ran. Review the diff before applying.'
));
assert.ok(allText(noChecksPanel).includes('Configure tests'));

const misleadingSkipped = {
    checks_run: 0,
    passed: true,
    results: [{ status: 'skipped', path: 'notes.txt' }],
};
assert.equal(evidence.codeTestEvidence(misleadingSkipped).status, 'no_checks');
assert.equal(
    evidence.codeApplyEvidenceValid({
        operation: 'code_apply',
        tests: noChecks,
    }),
    true,
);
assert.equal(
    evidence.codeApplyEvidenceValid({
        operation: 'code_apply',
        tests: passed,
    }),
    true,
);

const legacyPassed = {
    passed: true,
    results: [{ status: 'passed', path: 'legacy.js' }],
};
assert.equal(evidence.codeTestEvidence(legacyPassed).status, 'passed');
assert.equal(
    evidence.codeApplyEvidenceValid({
        operation: 'code_apply',
        tests: legacyPassed,
    }),
    true,
);

language = 'de';
assert.equal(
    evidence.codeTestEvidenceLabel(passed),
    'Tests bestanden · 2 Checks ausgeführt',
);
assert.equal(
    evidence.codeTestEvidenceLabel(noChecks),
    'Nicht getestet · Für diesen Workspace ist kein passender Test konfiguriert.',
);
let rerenders = 0;
window.MLXChatRendering.renderMessages = options => {
    rerenders++;
    assert.equal(options.contentUpdated, false);
};
listeners.get('mlx-language-changed')();
assert.equal(rerenders, 1);

assert.match(html, /id="workspaceTestCommands"/);
assert.match(html, /id="workspaceTestsSave"/);
assert.match(chatSource, /test_commands:\s*testCommands/);
assert.match(chatSource, /openTestConfiguration/);

console.log('Code evidence UI: passed, failed, no_checks, skipped and approval states passed.');
