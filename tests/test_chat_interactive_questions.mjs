import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/assets/chat/interactive-questions.js', 'utf8');
const html = fs.readFileSync('frontend/chat.html', 'utf8');
const generation = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const rendering = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');
const chat = fs.readFileSync('frontend/assets/chat.js', 'utf8');
const fence = String.fromCharCode(96).repeat(3);
const block = data => 'Einleitung\n\n' + fence + 'nobby-questions\n'
    + JSON.stringify(data) + '\n' + fence + '\n\nNachsatz';

class Element {
    constructor(tag) {
        this.tag = tag;
        this.children = [];
        this.listeners = {};
        this.attributes = {};
        this.value = '';
        this.checked = false;
        this.disabled = false;
        this.className = '';
        this._html = '';
        this._text = '';
        this.classList = {add: name => {this.className += ' ' + name;}};
    }
    set innerHTML(value) { this._html = value; this.children = []; }
    get innerHTML() { return this._html; }
    set textContent(value) { this._text = String(value); }
    get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
    append(...nodes) { this.children.push(...nodes); }
    appendChild(node) { this.children.push(node); return node; }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    focus() { this.focused = true; }
    fire(name) { return this.listeners[name]?.({preventDefault() {}}); }
}

function fixture(locale = 'de') {
    const storage = new Map();
    const input = new Element('textarea');
    const selector = new Element('select');
    let session = null, sent = '', saves = 0;
    const document = {
        documentElement: {lang: locale},
        createElement: tag => new Element(tag),
        getElementById: id => id === 'input' ? input
            : id === 'interactiveQuestionsMode' ? selector : null
    };
    const window = {
        localStorage: {
            getItem: key => storage.get(key) ?? null,
            setItem: (key, value) => storage.set(key, value)
        },
        MLXI18n: {getLocale: () => locale},
        MLXChatSessions: {currentSession: () => session, saveSessions: () => {saves++;}},
        MLXChatAttachments: {getAttachments: () => []},
        MLXChatRuntime: {isSwitching: () => false, autoResize() {}},
        MLXChatRendering: {renderMessages() {}},
        MLXChatGeneration: {
            isBusy: () => false,
            sendMessage: () => {sent = input.value; input.value = ''; return Promise.resolve();}
        }
    };
    vm.runInNewContext(source, {window, document, console, Date, Map, Set, String, JSON});
    return {
        api: window.MLXInteractiveQuestions,
        input, selector,
        setSession(value) {session = value;},
        get sent() {return sent;},
        get saves() {return saves;}
    };
}

const spec = {
    title: 'Drei Fragen',
    description: 'Bitte wählen',
    questions: [
        {label: 'Entscheidung?', type: 'single', options: ['Ja', 'Nein']},
        {label: 'Mehrfach?', type: 'multiple', options: ['A', 'B', 'C']},
        {label: 'Kommentar?', type: 'text', required: false}
    ],
    footer: 'Optional'
};
function find(root, pred) {
    const out = [];
    const visit = node => {
        if (pred(node)) out.push(node);
        for (const child of node.children || []) visit(child);
    };
    visit(root);
    return out;
}

test('question contract supports all controls and rejects invalid or excessive JSON', () => {
    const {api} = fixture();
    assert.equal(api.normalize(spec).questions.length, 3);
    assert.equal(api.normalize({...spec, questions: []}), null);
    assert.equal(api.normalize({...spec, questions: Array(5).fill(spec.questions[0])}), null);
    assert.equal(api.normalize({questions: [{label:'x',type:'single',options:['Same','Same']}]}), null);
    assert.equal(api.normalize({questions: [{label:'x',type:'custom'}]}), null);
    assert.equal(api.extract(block(spec)).spec.questions[1].type, 'multiple');
    assert.equal(api.extract('normal answer'), null);
    assert.equal(api.extract(fence + 'nobby-questions\n{broken}\n' + fence), null);
    assert.equal(api.extract(fence + 'nobby-questions\n' + 'x'.repeat(12001) + '\n' + fence), null);
});

test('partial streaming JSON is hidden and completed markdown stays readable', () => {
    const {api} = fixture();
    assert.equal(api.extract('Intro\n' + fence + 'nobby-questions\n{"questions":', true).loading, true);
    const parsed = api.extract(block(spec), false);
    assert.match(parsed.text, /Einleitung/);
    assert.match(parsed.text, /Nachsatz/);
    assert.doesNotMatch(parsed.text, /nobby-questions/);
    assert.equal(api.extract(fence + 'nobby-questions\n{"questions":', false), null);
});

test('modes persist locally and follow-up submissions are not questioned again', () => {
    const {api, selector} = fixture();
    api.init();
    assert.equal(selector.value, 'auto');
    const message = [{role:'user',content:'Welche Prioritäten brauche ich?'}];
    assert.match(api.instructionForTurn(message), /at least two independent/);
    selector.value = 'always'; selector.fire('change');
    assert.equal(api.getMode(), 'always');
    assert.match(api.instructionForTurn(message), /prefer asking concise/);
    assert.match(api.instructionForTurn([
        {role:'user',content:'Meine Antworten auf deine Rückfragen:\n1. Ja'}
    ]), /Do not ask the same questions again/);
    assert.match(api.instructionForTurn([{role:'user',content:'Bitte beantworte meine ursprüngliche Frage ohne weitere Rückfragen.'}]), /without further questions/);
    assert.match(api.instructionForTurn([{role:'user',content:'My answers to your follow-up questions:\n1. Yes'}]), /Do not ask the same questions again/);
    selector.value = 'off'; selector.fire('change');
    assert.equal(api.instructionForTurn(message), '');
});

test('required fields validate and selected answers go through the existing chat', () => {
    const f = fixture();
    const message = {role:'assistant',content:block(spec),response_pending:false};
    const session = {id:'test-chat',messages:[{role:'user',content:'Beratung?'},message]};
    f.setSession(session);
    const parent = new Element('div');
    assert.equal(f.api.enhance(parent,message,session,1,x=>x), true);
    const form = find(parent,n=>n.tag==='form')[0];
    form.fire('submit');
    assert.equal(f.sent, '');
    assert.match(form.textContent, /Pflichtfragen/);
    const radios = find(form,n=>n.tag==='input'&&n.type==='radio');
    const checks = find(form,n=>n.tag==='input'&&n.type==='checkbox');
    radios[1].checked = true; radios[1].fire('change');
    checks[0].checked = true; checks[0].fire('change');
    checks[2].checked = true; checks[2].fire('change');
    form.fire('submit');
    assert.match(f.sent, /Nein/);
    assert.match(f.sent, /A, C/);
    assert.equal(f.saves, 1);
    assert.equal(message.interactive_answers.answers[0], 'Nein');
    assert.equal(message.interactive_answers.answers[1].length, 2);
    const restored = new Element('div');
    assert.equal(f.api.enhance(restored,message,session,1,x=>x), true);
    assert.match(restored.textContent, /Antworten gesendet/);
    assert.equal(find(restored,n=>n.tag==='button').length, 0);
});

test('draft text is protected and skipped forms cannot submit twice', () => {
    const f = fixture();
    const message = {role:'assistant',content:block(spec)};
    const session = {id:'s2',messages:[message]};
    f.setSession(session);
    const parent = new Element('div');
    f.api.enhance(parent,message,session,0,x=>x);
    const skip = find(parent,n=>n.tag==='button'&&n.type==='button')[0];
    f.input.value = 'Unsent draft';
    skip.fire('click');
    assert.equal(f.sent, '');
    assert.equal(f.input.value, 'Unsent draft');
    f.input.value = '';
    skip.fire('click');
    assert.match(f.sent, /ohne weitere Rückfragen/);
    assert.equal(message.interactive_answers.skipped, true);
    skip.fire('click');
    assert.equal(f.saves, 1);
});

test('UI is mounted in the normal chat flow and does not execute model markup', () => {
    assert.match(html, /interactive-questions\.js\?v=20261028/);
    assert.match(html, /interactive-questions\.css\?v=20261028/);
    assert.match(html, /id="interactiveQuestionsMode"/);
    assert.match(generation, /MLXInteractiveQuestions\?\.instructionForTurn/);
    assert.match(generation, /isBusy: \(\) => getGenerating\(\)/);
    assert.match(rendering, /MLXInteractiveQuestions\?\.enhance/);
    assert.match(chat, /MLXInteractiveQuestions\?\.init/);
    assert.doesNotMatch(source, /eval\(|new Function|JSON\.parse\(.*innerHTML/);
});
