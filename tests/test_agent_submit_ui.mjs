import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const runtime = fs.readFileSync(new URL('../frontend/assets/chat/runtime.js', import.meta.url), 'utf8');
const generation = fs.readFileSync(new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8');
const update = runtime.match(/function updateSendButton\(\) \{[\s\S]*?\n\}/)?.[0];
assert.ok(update, 'send button updater exists');

const button = { textContent: '', disabled: false, classList: {
    add() {}, remove() {},
} };
let active = true;
const context = {
    sendButton: button,
    isSwitching: () => false,
    isGenerating: () => active,
    window: { MLXChatGeneration: { isAgentRunning: () => active } },
};
vm.runInNewContext(`${update}\nupdateSendButton();`, context);
assert.equal(button.disabled, true);
assert.equal(button.textContent, '…');

active = false;
vm.runInNewContext('updateSendButton();', context);
assert.equal(button.disabled, false);
assert.equal(button.textContent, '↑');

assert.match(generation, /async function sendMessage\(options = \{\}\) \{\s*if \(agentRunActive\) return;/);
assert.match(generation, /agentRunActive = false;\s*setGenerating\(false\);/);
console.log('Agent submit is blocked during a run and restored afterwards.');
