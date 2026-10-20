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
const setting = enabled => ({ settings: { adaptive_response_length: enabled } });
const user = content => ({ role: 'user', content });
const reply = (tokens, finish = 'stop') => ({
    role: 'assistant', content: 'Jenny looks over and smiles.',
    model_metrics: { calls: [{ purpose: 'chat.stream', status: 'completed', finish_reason: finish,
        usage: { output_tokens: tokens, count_method: 'upstream' } }] }
});
const history = (current = 'Und jetzt?', r = [reply(20),reply(25),reply(30)]) =>
    [user('Hallo'),r[0],user('Weiter'),r[1],user('Und?'),r[2],user(current)];

test('opt-in, three brief normal replies trigger one-turn instruction', () => {
    assert.equal(guidance(setting(false), history()), '');
    assert.match(guidance(setting(true), history()), /three to five substantive sentences/);
    assert.match(guidance(setting(true), history()), /never write/);
});
test('no guidance for real length limits, failed or incomplete streams', () => {
    for (const bad of [
        reply(72), reply(20,'length'), reply(20,null),
        { ...reply(20), response_pending:true },
        { ...reply(20), tool_result:{} },
        { ...reply(20), model_metrics:undefined }
    ]) {
        assert.equal(guidance(setting(true), history('Weiter', [bad,reply(24),reply(26)])), '');
    }
});
test('recent substantive answer breaks the short-answer streak', () => {
    assert.equal(guidance(setting(true),history('Weiter',[reply(20),reply(190),reply(20)])), '');
});
test('explicit short user requests and long/nontext turns are respected', () => {
    assert.equal(guidance(setting(true),history('Antworte bitte kurz.')), '');
    assert.equal(guidance(setting(true),history('Nur ein Satz.')), '');
    assert.equal(guidance(setting(true),history('x'.repeat(321))), '');
    assert.equal(guidance(setting(true),[...history().slice(0,-1),{role:'user',content:[{type:'text',text:'ok'}]}]), '');
});
test('UI and persistence are wired only as opt-in and per chat', () => {
    assert.match(html, /id="adaptiveResponseLength"/);
    assert.match(runtime, /adaptive_response_length: false/);
    assert.match(runtime, /settings\.adaptive_response_length = adaptiveResponseLength\.checked/);
    assert.match(generation, /MLXChatResponseLength\?\.instructionForTurn/);
    assert.match(generation, /generationSettings\.max_tokens/);
    assert.match(html, /response-length\.js\?v=20261020-adaptive-roleplay/);
});
