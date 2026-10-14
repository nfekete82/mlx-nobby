import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const generation = readFileSync(new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8');

test('attachment image edit retains its chosen model without a second model picker', () => {
    assert.match(generation, /const hasAttachmentEditModelPicker\s*=\s*resolvedTarget === 'image_edit'\s*&&\s*imageAttachmentMode === 'edit'\s*&&\s*imageFiles\.length > 0/);
    assert.match(generation, /hasAttachmentEditModelPicker\s*\?\s*\(options\?\.referenceEdit\?\.model \|\| 'auto'\)/);
    assert.match(generation, /const imageModelSelectable\s*=\s*mediaQualityKind === 'image'\s*&&\s*!hasAttachmentEditModelPicker/);
    assert.match(generation, /mediaQualityKind === 'image'\s*\? selectedImageModel\s*:\s*null/);
});
