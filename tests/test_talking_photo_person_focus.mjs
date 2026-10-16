import assert from 'node:assert/strict';
import fs from 'node:fs';

const js = fs.readFileSync(new URL('../frontend/assets/chat/talking-photo.js', import.meta.url), 'utf8');

assert.match(js, /let personFocus = null/);
assert.match(js, /preview\.addEventListener\('click', event =>/);
assert.match(js, /talkingPhotoPersonFocusReset/);
assert.match(js, /personFocus = null;\s*focusReset\.hidden = true;/);
assert.match(js, /personFocus = \{x, y\}/);
assert.match(js, /async function focusedImageDataUrl\(file, focus\)/);
assert.match(js, /Math\.min\(src\.width - width/);
assert.match(js, /Math\.min\(src\.height - height/);
assert.match(js, /drawImage\(src, sx, sy, width, height, 0, 0, width, height\)/);
assert.match(js, /await focusedImageDataUrl\(file, personFocus\)/);
console.log('Talking Photo person focus selection and crop contract passed.');
