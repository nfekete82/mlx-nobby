import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Python supplies the actual production HTTP response; the JS suite also runs
// this scenario against the tracked module. Batch fixtures are real local jobs.
const settingsSource = fs.readFileSync(process.argv[2] || 'frontend/assets/chat/image-settings.js', 'utf8');
const fixtures = JSON.parse(fs.readFileSync('tests/fixtures/image_variant_batches.json', 'utf8'));
class Element {
    constructor(tag = 'div') {
        this.tagName = tag; this.children = []; this.dataset = {}; this.style = {};
        this.className = ''; this.listeners = {}; this._text = '';
        this.classList = {contains: name => this.className.split(' ').includes(name),
            add: name => {this.className += ' ' + name;}};
    }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this._text = String(value); this.children = []; }
    append(...children) { for (const child of children) this.appendChild(child); }
    appendChild(child) {
        if (child.tagName === '#fragment') { this.append(...child.children); return child; }
        child.remove(); child.parentNode = this; this.children.push(child); return child;
    }
    prepend(child) { this.appendChild(child); this.children.unshift(this.children.pop()); }
    remove() { if (this.parentNode) {this.parentNode.children = this.parentNode.children.filter(c => c !== this); this.parentNode = null;} }
    replaceChild(next, previous) { const index = this.children.indexOf(previous); next.parentNode = this; previous.parentNode = null; this.children[index] = next; }
    matches(selector) {
        const [tag, ...classes] = selector.split('.');
        return (!tag || tag === this.tagName) && classes.every(name => this.classList.contains(name));
    }
    querySelectorAll(selector) { return this.children.flatMap(c => [...(c.matches(selector) ? [c] : []), ...c.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
}
const container = new Element();
const document = {createElement: tag => new Element(tag), createDocumentFragment: () => new Element('#fragment'),
    getElementById: id => id === 'messagesInner' ? container : null, addEventListener() {},
    querySelectorAll: () => [], head: new Element('head'), documentElement: {lang: 'en'}};
let activeSession;
let batchResponse;
let renderFailure = false;
let saves = 0;
let resumes = 0;
const posts = [];
const warnings = [];
const window = {MLXI18n: {t: (_key, fallback) => fallback},
    MLXChatSessions: {currentSession: () => activeSession, saveSessions: () => {saves++;}}};
window.window = window;
const context = {window, document, console: {...console, warn: (...args) => warnings.push(args)},
    crypto: {randomUUID: () => 'test-trace'}, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    fetch: async (url, options) => {
        if (url.startsWith('/i18n/')) return {ok: false};
        posts.push({url, options});
        return {ok: true, json: async () => structuredClone(batchResponse)};
    }};
vm.runInNewContext(fs.readFileSync('frontend/assets/chat/generation.js', 'utf8'), context);
vm.runInNewContext(fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8'), context);
const cards = window.MLXChatRendering.__test;
const renderMessages = () => {
    if (renderFailure) throw new ReferenceError('injected gallery render failure');
    container.children = [];
    for (const message of activeSession.messages) {
        const article = new Element('article'); article.className = 'message ' + message.role;
        const image = cards.renderImageArtifactCard(message);
        const job = cards.renderImageJobCard(message);
        if (image) article.appendChild(image);
        if (job) article.appendChild(job);
        container.appendChild(article);
    }
};
window.MLXChatRendering.renderMessages = renderMessages;
window.MLXChatRendering.renderAll = renderMessages;
window.MLXChatGeneration.resumeImageJobsForSession = () => {resumes++;};
vm.runInNewContext(settingsSource, context);
vm.runInNewContext(fs.readFileSync('frontend/assets/chat/image-variant-gallery.js', 'utf8'), context);
const api = window.MLXImageRegenerate;
const reset = fixture => {
    batchResponse = structuredClone(fixture);
    activeSession = {id: fixture.base.data.job.chat_id, revision: 0, workspace: {}, messages: [
        {role: 'user', content: 'erstelle ein bild von einer frau'},
        {role: 'assistant', content: '', tool_result: structuredClone(fixture.base), image_job: structuredClone(fixture.base.data.job)}]};
};
for (const fixture of [fixtures.three, fixtures.six]) {
    reset(fixture);
    const beforeSaves = saves;
    const base = activeSession.messages[1];
    const messages = await api.submitVariantBatch(fixture.base.artifacts[0], fixture.variant_count, {includeBase: true, firstMessage: base});
    assert.equal(messages.length, fixture.variant_count - 1);
    assert.equal(activeSession.messages.length, fixture.variant_count + 1);
    assert.equal(saves, beforeSaves + 1, 'one canonical persistence per response');
    assert.equal(container.querySelectorAll('.image-variant-gallery').length, 1);
    assert.equal(container.querySelectorAll('.image-variant-slot').length, fixture.variant_count);
    assert.equal(container.querySelectorAll('.image-job-card').length, 0, 'no separate pending cards');
    assert.equal(base.image_variant_group_id, fixture.variant_group_id);
    assert.ok(container.textContent.includes('1/' + fixture.variant_count));
    const selected = fixture.base.artifacts[0].artifact_id;
    activeSession.workspace.active_artifact_id = selected;
    batchResponse.jobs[0].status = batchResponse.jobs[0].data.job.status = 'completed';
    batchResponse.jobs[0].artifacts = [{...fixture.base.artifacts[0], image_id: 'second-image', artifact_id: 'second-artifact'}];
    assert.equal(await api.refreshImageVariants(fixture.variant_group_id), true);
    assert.ok(container.textContent.includes('2/' + fixture.variant_count));
    assert.equal(activeSession.workspace.active_artifact_id, selected);
    // Re-applying a persisted group on reload retains one message per slot.
    activeSession = JSON.parse(JSON.stringify(activeSession));
    assert.equal(await api.refreshImageVariants(fixture.variant_group_id), true);
    assert.equal(activeSession.messages.length, fixture.variant_count + 1);
    assert.equal(container.querySelectorAll('.image-variant-gallery').length, 1);
}
// A successful POST followed by a render exception remains a started batch.
reset(fixtures.three); renderFailure = true;
const beforeResumes = resumes;
assert.equal((await api.submitVariantBatch(fixtures.three.base.artifacts[0], 3,
    {includeBase: true, firstMessage: activeSession.messages[1]})).length, 2);
assert.equal(activeSession.messages.length, 4);
assert.equal(resumes, beforeResumes + 1);
assert.ok(activeSession.messages[1].image_variant_ui_error.includes('has started'));
assert.ok(activeSession.messages.every(m => !m.content.includes('could not be started')));
assert.equal(posts.filter(p => p.url.endsWith('/variants')).length, 3, 'one POST per requested batch');
renderFailure = false;
window.MLXChatRendering.renderAll();
assert.equal(container.querySelectorAll('.image-variant-gallery').length, 1);
// Cached pre-#93 action code failed here. Optional actions cannot break collapse.
window.MLXChatGeneration.createImageUpscaleMenu = () => {throw new ReferenceError('variants is not defined');};
window.MLXChatRendering.renderAll();
assert.equal(container.querySelectorAll('.image-variant-gallery').length, 1);
assert.equal(container.querySelectorAll('.image-job-card').length, 0);
assert.ok(warnings.some(args => String(args[0]).includes('optional image actions')));
// Full validation precedes every session mutation.
reset(fixtures.three);
batchResponse.jobs[1].data.job.variant_index = 2;
const before = JSON.stringify(activeSession);
assert.equal(await api.submitVariantBatch(fixtures.three.base.artifacts[0], 3,
    {includeBase: true, firstMessage: activeSession.messages[1]}), null);
assert.equal(JSON.stringify(activeSession), before);
console.log('Served variant runtime: real 3/6 batches, atomic application, render failure, gallery collapse and reload passed.');
