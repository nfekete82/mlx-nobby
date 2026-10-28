import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../frontend/assets/chat/talking-photo.js', import.meta.url), 'utf8');

assert.match(source, /localText\('Videoqualität', 'Video quality'\)/);
assert.match(source, /talkingPhotoEngine/);
assert.match(source, /Schnell · LTX Distilled \(8\+3 Schritte\)/);
assert.match(source, /Hohe Qualität · LTX direkt \(15\+3 Schritte\)/);
assert.match(source, /Maximal · LTX direkt \(30\+3 Schritte\)/);
assert.match(source, /'ltx-max'/);
assert.match(source, /Höhere Schärfe oder besserer Lip-Sync sind nicht garantiert/);
assert.match(source, /function savedQualityEngine\(\)/);
assert.match(source, /localStorage\.getItem\(QUALITY_STORAGE_KEY\)/);
assert.match(source, /QUALITY_ENGINES\.has\(saved\)/);
assert.match(source, /localStorage\.setItem\(QUALITY_STORAGE_KEY, value\)/);
assert.match(source, /engineSelect\.value = savedQualityEngine\(\)/);
assert.match(source, /rememberQualityEngine\(engineSelect\.value\)/);
assert.match(source, /refreshQualityHint\(\)/);
assert.match(source, /engine,\s*person_focus: personFocus/);
assert.match(source, /a visible quality improvement is not guaranteed/i);
console.log('Talking Photo quality picker contract passed.');
