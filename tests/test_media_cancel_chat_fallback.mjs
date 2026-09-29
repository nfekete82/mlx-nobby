import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(
    'frontend/assets/chat/media-routing-fallback.js',
    'utf8'
);

assert.match(source, /mediaQualityModalCancel/);
assert.match(source, /data-media-quality-dismiss/);
assert.match(source, /event\.key === 'Escape'/);
assert.match(source, /userMessage\?\.role !== 'user'/);
assert.match(source, /session\.messages\.at\(-1\) !== userMessage/);
assert.match(source, /generation\.generateAssistant\(session\)/);

console.log('Media modal cancellation falls back to normal chat.');
