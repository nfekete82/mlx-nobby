import assert from 'node:assert/strict';
import fs from 'node:fs';

const js = fs.readFileSync(new URL('../frontend/assets/chat/talking-photo.js', import.meta.url), 'utf8');

assert.match(js, /let personFocus = null/);
assert.match(js, /preview\.addEventListener\('click', event =>/);
assert.match(js, /talkingPhotoPersonFocusReset/);
assert.match(js, /personFocus = \{x, y\}/);
assert.match(js, /engineSelect\.value = 'fast'/);
assert.match(js, /engineSelect\.disabled = true/);
assert.match(js, /engineSelect\.disabled = false/);
assert.match(js, /const imageDataUrl = await fileToDataUrl\(file\)/);
assert.match(js, /person_focus: personFocus/);
assert.match(js, /engine: personFocus \? 'fast' : engine/);
assert.doesNotMatch(js, /await focusedImageDataUrl/);
console.log('Talking Photo full-scene person selection contract passed.');
