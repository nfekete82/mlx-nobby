import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const js = readFileSync(path.join(root, 'frontend/assets/chat/runtime.js'), 'utf8');
const html = readFileSync(path.join(root, 'frontend/chat.html'), 'utf8');
const guide = readFileSync(path.join(root, 'docs/JUGGERNAUT_RAGNAROK_PROMPTING.md'), 'utf8');

assert.match(js, /'juggernaut-ragnarok':\s*\{/);
assert.match(js, /832x1216/);
assert.match(js, /30-40 steps, CFG 3-6/);
assert.match(js, /negative prompt should initially be empty/);
assert.match(js, /around 75 CLIP tokens/);
assert.match(js, /Hi-res recommendation.*NOT an implemented MLX-Nobby rendering option/);
assert.match(html, /<option value="juggernaut-ragnarok">Juggernaut Ragnarok \(Prompting\)<\/option>/);
assert.match(html, /runtime\.js\?v=20261102-ragnarok-prompt-knowledge/);
assert.match(guide, /RunDiffusion.*2026-10-22/);
console.log('Ragnarok prompt preset and knowledge guide: OK');
