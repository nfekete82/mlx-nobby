import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const attach = readFileSync(new URL('../frontend/assets/chat/attachments.js', import.meta.url), 'utf8');
const generate = readFileSync(new URL('../frontend/assets/chat/generation.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');

test('Office and archive attachments are selectable', () => {
  for (const ext of ['docx', 'xlsx', 'xls', 'zip']) {
    assert.ok(attach.includes("'" + ext + "'"));
    assert.ok(html.includes('.' + ext));
  }
});

test('Binary attachments do not enter the normal chat context', () => {
  assert.ok(attach.includes("kind: 'office'"));
  assert.ok(attach.includes("file.kind !== 'office'"));
  assert.ok(attach.includes("context_omitted: true"));
});

test('Office processing uses the bounded, separate local upload endpoint', () => {
  assert.ok(generate.includes("file.kind === 'office'"));
  assert.ok(generate.includes("'/api/mlx/office/process'"));
  assert.ok(generate.includes("form.append('instruction', prompt)"));
  assert.ok(generate.includes("result.download_url"));
  assert.ok(generate.includes("MLXChatAttachments.clearAttachments()"));
});
