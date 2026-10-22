import assert from 'node:assert/strict';
import fs from 'node:fs';

const js = fs.readFileSync(new URL('../frontend/assets/chat/talking-photo.js', import.meta.url), 'utf8');

assert.match(js, /let personFocus = null/);
assert.match(js, /preview\.addEventListener\('click', event =>/);
assert.match(js, /talkingPhotoPersonFocusReset/);
assert.match(js, /talkingPhotoFocusMarker/);
assert.match(js, /positionFocusMarker\(\)/);
assert.match(js, /focusMarker\.hidden = false/);
assert.match(js, /personFocus = \{x, y\}/);
assert.doesNotMatch(js, /engineSelect\.value === 'quality'/);
assert.doesNotMatch(js, /engineSelect\.value = 'fast'/);
assert.doesNotMatch(js, /engineSelect\.disabled = true/);
assert.match(js, /const imageDataUrl = await fileToDataUrl\(file\)/);
assert.match(js, /person_focus: personFocus/);
assert.match(js, /engine,/);
assert.match(js, /motion: 'natural'/);
assert.doesNotMatch(js, /await focusedImageDataUrl/);
console.log('Talking Photo LTX-only speaker selection contract passed.');
