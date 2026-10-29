import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import test from 'node:test';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = readFileSync(resolve(root, 'frontend/assets/chat/generation.js'), 'utf8');
const html = readFileSync(resolve(root, 'frontend/chat.html'), 'utf8');

test('text-only prompts do not bind old image artifacts for editing', () => {
    assert.match(source, /let activeArtifactIdForEdit =\s*!imageFiles\.length[^;]+explicitVideoAnimateRequest/s);
    assert.match(source, /if \(resolvedTarget === 'image_edit' && !imageFiles\.length\) \{\s*console\.warn\([^;]+;\s*resolvedTarget = 'chat';/);
    assert.doesNotMatch(source, /!imageFiles\.length && activeWorkspaceImageArtifact\?\.semantic_operation === 'reference_generate'/);
});

test('clear video requests never silently fall back to normal chat on route failure', () => {
    assert.match(source, /if \(isVideoRequest\(prompt\)\) \{\s*throw new Error\(/);
    assert.match(html, /generation\.js\?v=20261029-text-only-media-routing/);
});
