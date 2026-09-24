import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync('frontend/chat.html', 'utf8');
const runtime = fs.readFileSync('frontend/assets/chat/runtime.js', 'utf8');
const generation = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const rendering = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');
const css = fs.readFileSync('frontend/assets/chat.css', 'utf8');

assert.match(html, /id="mediaQuality"/);
assert.match(html, /value="fast"/);
assert.match(html, /data-media-quality="preview"/);
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
assert.match(generation, /preview: Object\.freeze\(\[2\]\)/);
assert.match(generation, /fast: Object\.freeze\(\[5, 6, 8, 10, 20\]\)/);
assert.match(generation, /quality: Object\.freeze\(\[5\]\)/);
assert.match(generation, /const mediaQualityKind/);
assert.match(generation, /if \(mediaQualityKind\)/);
assert.match(generation, /\/api\/mlx\/chat\/actions\/route/);
assert.match(generation, /resolvedTarget === 'image_edit'/);
assert.match(generation, /resolved_target: resolvedTarget/);
assert.match(generation, /const serverTarget = String/);
assert.match(generation, /resolvedTarget !== 'image_edit'/);
assert.match(generation, /let acceptEnter = false/);
assert.match(generation, /requestAnimationFrame\(\(\) => \{\s*acceptEnter = true/);
assert.match(rendering, /artifact\.quality \? 'Qualität: '/);
assert.match(rendering, /preview: 'Vorschau'/);


assert.match(html, /id="mediaFormatField"/);
assert.match(html, /id="mediaFormat"/);
assert.match(generation, /const VIDEO_FORMATS/);
assert.match(generation, /const IMAGE_FORMATS/);
assert.match(generation, /IMAGE_SIZES_BY_FORMAT/);
assert.match(generation, /auto_size: true/);
assert.match(generation, /videoAspectRatioForFormat/);
assert.match(generation, /imageOptionsForRequest/);
assert.match(generation, /aspect_ratio:/);

assert.match(css, /media-quality-option\[hidden\]/);
assert.match(css, /repeat\(auto-fit, minmax\(135px, 1fr\)\)/);
assert.match(generation, /Querformat 16:9/);
assert.match(generation, /Hochformat 9:16/);

console.log('Media quality default, session persistence, request forwarding, and artifact metadata passed.');
