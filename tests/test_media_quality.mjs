import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync('frontend/chat.html', 'utf8');
const runtime = fs.readFileSync('frontend/assets/chat/runtime.js', 'utf8');
const generation = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const rendering = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');

assert.match(html, /id="mediaQuality"/);
assert.match(html, /value="fast"/);
assert.match(html, /value="standard"[^>]*selected/);
assert.match(html, /value="quality"/);
assert.match(runtime, /const DEFAULT_MEDIA_QUALITY = 'standard'/);
assert.match(runtime, /media_quality: DEFAULT_MEDIA_QUALITY/);
assert.match(runtime, /settings\.media_quality = normalizeMediaQuality/);
assert.match(html, /id="mediaQualityModal"/);
assert.match(html, /id="videoDurationField"/);
assert.match(html, /id="videoDuration"/);
for (const duration of [5, 6, 8, 10, 20]) {
    assert.match(html, new RegExp(`option value="${duration}"`));
}
assert.match(generation, /quality: selectedMediaQuality/);
assert.match(generation, /videoOptionsForRequest/);
assert.match(generation, /VIDEO_DURATIONS_BY_QUALITY/);
assert.match(generation, /fast: Object\.freeze\(\[5, 6, 8, 10, 20\]\)/);
assert.match(generation, /quality: Object\.freeze\(\[5\]\)/);
assert.match(generation, /const mediaQualityKind/);
assert.match(generation, /if \(mediaQualityKind\)/);
assert.match(rendering, /artifact\.quality \? 'Qualität: '/);

console.log('Media quality default, session persistence, request forwarding, and artifact metadata passed.');
