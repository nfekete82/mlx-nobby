import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const root = new URL('../frontend/', import.meta.url);
const helper = readFileSync(new URL('assets/chat/response-length.js', root), 'utf8');
const html = readFileSync(new URL('chat.html', root), 'utf8');
const runtime = readFileSync(new URL('assets/chat/runtime.js', root), 'utf8');
const generation = readFileSync(new URL('assets/chat/generation.js', root), 'utf8');
const sandbox = { window: {} };
vm.runInNewContext(helper, sandbox);
const guidance = sandbox.window.MLXChatResponseLength.instructionForTurn;

const setting = (automatic, preset = 'custom', systemPrompt = '') =>
    ({ settings: { adaptive_response_auto: automatic, preset_id: preset, system_prompt: systemPrompt } });
const user = content => ({ role: 'user', content });
const reply = (tokens, finish = 'stop', content = 'Fine, thanks.') => ({
    role: 'assistant', content,
    model_metrics: { calls: [{ purpose: 'chat.stream', status: 'completed', finish_reason: finish,
        usage: { output_tokens: tokens, count_method: 'upstream' } }] }
});
const history = (current = 'Und jetzt?', r = [reply(20),reply(25),reply(30)]) =>
    [user('Hallo'),r[0],user('Weiter'),r[1],user('Und?'),r[2],user(current)];

test('automatic correction is enabled for existing and new chats unless explicitly disabled', () => {
    assert.match(guidance(setting(undefined), history()), /unusually short/);
    assert.match(guidance(setting(true), history()), /actual conversation/); // replaced below
    assert.equal(guidance(setting(false), history()), '');
    assert.match(runtime, /adaptive_response_auto: true/);
    assert.match(runtime, /settings\.adaptive_response_auto = adaptiveResponseLength\.checked/);
});
test('roleplay style is detected from preset, persona prompt or scene narration', () => {
    assert.match(guidance(setting(true, 'roleplay'), history()), /fitting actions and dialogue/);
    assert.match(guidance(setting(true, 'custom', 'Du spielst ein Rollenspiel'), history()), /Stay in/);
    const scene = history('Und jetzt?', [
        reply(25,'stop','Jenny blinzelt und lächelt.'),
        reply(26,'stop','Jenny schaut auf.'),
        reply(21,'stop','Jenny flüstert etwas.')
    ]);
    assert.match(guidance(setting(true), scene), /user character/);
});
test('ordinary conversations get balanced guidance, never forced 3-5 sentence roleplay', () => {
    const text = guidance(setting(true), history('Kannst du das näher erklären?'));
    assert.match(text, /open-ended question/);
    assert.match(text, /simple factual questions concise/);
    assert.doesNotMatch(text, /user character/);
});
test('simple fact queries and explicitly short responses are not inflated', () => {
    for (const text of ['Wer ist das?', 'Wie viel kostet es?', 'Wann war das?', 'Only one sentence.', 'Nur ein Satz.', 'Antworte bitte kurz.']) {
        assert.equal(guidance(setting(true), history(text)), '', text);
    }
});
test('no guidance for limit reached, failed, pending, tools or missing metrics', () => {
    for (const bad of [
        reply(71), reply(20,'length'), reply(20,null),
        { ...reply(20), response_pending:true },
        { ...reply(20), tool_result:{} },
        { ...reply(20), model_metrics:undefined }
    ]) {
        assert.equal(guidance(setting(true), history('Weiter', [bad,reply(24),reply(26)])), '');
    }
});
test('substantive answer breaks streak, long and non-text prompts bypass steering', () => {
    assert.equal(guidance(setting(true),history('Weiter',[reply(20),reply(190),reply(20)])), '');
    assert.equal(guidance(setting(true),history('x'.repeat(321))), '');
    assert.equal(guidance(setting(true),[...history().slice(0,-1),{role:'user',content:[{type:'text',text:'ok'}]}]), '');
});
test('UI, cache and generation integration keep corrections ephemeral', () => {
    assert.match(html, /id="adaptiveResponseLength" type="checkbox" checked/);
    assert.match(html, /response-length\.js\?v=20261020-auto-conversation/);
    assert.match(html, /runtime\.js\?v=20261020-auto-conversation/);
    assert.match(generation, /MLXChatResponseLength\?\.instructionForTurn/);
    assert.match(generation, /session, originalInferenceMessages/);
    assert.match(generation, /generationSettings\.max_tokens/);
});
