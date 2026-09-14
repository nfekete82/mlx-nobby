import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';


const source = fs.readFileSync(
    new URL('../frontend/assets/chat/rendering.js', import.meta.url),
    'utf8',
);
const catalogs = {
    en: JSON.parse(fs.readFileSync(new URL('../frontend/i18n/en.json', import.meta.url))),
    de: JSON.parse(fs.readFileSync(new URL('../frontend/i18n/de.json', import.meta.url))),
};
let language = 'en';

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
        this.hidden = false;
        this.open = false;
        this.attributes = {};
        this.listeners = {};
        this.classList = {
            add: (...names) => {
                this.className = [this.className, ...names]
                    .filter(Boolean)
                    .join(' ');
            },
        };
    }
    appendChild(child) { this.children.push(child); return child; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
    click() { this.listeners.click?.(); }
}

function findByClass(element, className) {
    if (String(element.className).split(/\s+/).includes(className)) {
        return element;
    }
    for (const child of element.children) {
        const found = findByClass(child, className);
        if (found) return found;
    }
    return null;
}

function findByTag(element, tag) {
    if (element.tag === tag) return element;
    for (const child of element.children) {
        const found = findByTag(child, tag);
        if (found) return found;
    }
    return null;
}

const listeners = new Map();
const document = {
    getElementById() { return new Element(); },
    createElement(tag) { return new Element(tag); },
    addEventListener(name, callback) { listeners.set(name, callback); },
    querySelectorAll() { return []; },
};
const window = { MLXI18n: { t: translation } };
window.window = window;

vm.runInNewContext(source, { document, window, console }, {
    filename: 'frontend/assets/chat/rendering.js',
});

const { renderAgentCard } = window.MLXChatRendering.__test;
const steps = [
    {
        action: 'system_status',
        status: 'completed',
        reason: 'Inspect the local system',
        result: { ok: true },
    },
    {
        action: 'disk_usage',
        status: 'running',
        reason: 'Find large files',
    },
];
const message = {
    agent_run: {
        status: 'running',
        goal: 'Analyze storage usage on this Mac',
        steps,
        pending_action: null,
    },
};

let card = renderAgentCard(message);
let details = findByClass(card, 'agent-card-details');
let toggle = findByClass(card, 'agent-card-toggle');
let metadata = findByClass(card, 'agent-card-metadata');
assert.equal(details.hidden, true, 'Agent steps must be collapsed by default');
assert.equal(toggle.getAttribute('aria-expanded'), 'false');
assert.equal(toggle.textContent, 'Show details ▾');
assert.match(metadata.textContent, /2 steps/);
assert.match(metadata.textContent, /Running/);
assert.ok(findByClass(details, 'agent-step'), 'Collapsed steps remain in the DOM');

toggle.click();
assert.equal(details.hidden, false);
assert.equal(toggle.getAttribute('aria-expanded'), 'true');
assert.equal(toggle.textContent, 'Hide details ▴');
const technicalDetails = findByTag(details, 'details');
assert.ok(technicalDetails, 'Nested technical details remain available');
technicalDetails.open = true;
assert.equal(technicalDetails.open, true);

message.agent_run = {
    ...message.agent_run,
    status: 'completed',
    steps: steps.map(step => ({ ...step, status: 'completed' })),
};
card = renderAgentCard(message);
details = findByClass(card, 'agent-card-details');
toggle = findByClass(card, 'agent-card-toggle');
metadata = findByClass(card, 'agent-card-metadata');
assert.equal(details.hidden, false, 'Live updates preserve the manual choice');
assert.match(metadata.textContent, /Completed/);

toggle.click();
message.agent_run = { ...message.agent_run, status: 'failed' };
card = renderAgentCard(message);
details = findByClass(card, 'agent-card-details');
metadata = findByClass(card, 'agent-card-metadata');
assert.equal(details.hidden, true, 'Manual collapse survives status updates');
assert.match(metadata.textContent, /Failed/);

const cancelled = renderAgentCard({
    agent_run: {
        status: 'cancelled',
        goal: 'Cancelled diagnostic',
        steps: [{ action: 'system_status', status: 'failed' }],
    },
});
assert.equal(findByClass(cancelled, 'agent-card-details').hidden, true);
assert.match(findByClass(cancelled, 'agent-card-metadata').textContent, /Cancelled/);

language = 'de';
const german = renderAgentCard({
    agent_run: {
        status: 'completed',
        goal: 'Speicherplatz analysieren',
        steps: [{ action: 'disk_usage', status: 'completed' }],
    },
});
assert.equal(findByClass(german, 'agent-card-toggle').textContent, 'Details anzeigen ▾');
assert.match(findByClass(german, 'agent-card-metadata').textContent, /1 Schritt/);

console.log('Agent card collapse, state updates, nested details, and i18n passed.');
