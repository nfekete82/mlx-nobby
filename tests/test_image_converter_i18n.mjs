import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync('frontend/converter.html', 'utf8');
const js = fs.readFileSync('frontend/assets/image-converter.js', 'utf8');
const parent = fs.readFileSync('frontend/assets/chat/image-converter-workspace.js', 'utf8');
const dictionaries = JSON.parse(fs.readFileSync('frontend/i18n/image-converter.json', 'utf8'));

const keys = ['header', 'heading', 'intro', 'drop', 'format', 'png', 'quality',
  'maxEdge', 'original', 'alpha', 'submit', 'footer', 'none',
  'file', 'files', 'more', 'working', 'done', 'error', 'heic', 'several'];
for (const key of keys) {
  if (!['none', 'file', 'files', 'more', 'working', 'done', 'error', 'heic', 'several'].includes(key)) {
    assert.match(html, new RegExp('data-converter-i18n="' + key + '"'), key);
  }
  assert.equal(typeof dictionaries.en[key], 'string', 'Missing EN ' + key);
  assert.equal(typeof dictionaries.de[key], 'string', 'Missing DE ' + key);
}
assert.deepEqual(Object.keys(dictionaries.en).sort(), Object.keys(dictionaries.de).sort());
assert.equal(dictionaries.de.format, 'Zielformat');
assert.equal(dictionaries.en.format, 'Output format');
assert.match(html, /<html lang="en">/);
assert.match(js, /fetch\('\/i18n\/image-converter\.json'/);
assert.match(js, /document\.documentElement\.lang = language/);
assert.match(js, /window\.addEventListener\('message'/);
assert.match(js, /event\.source !== window\.parent/);
assert.match(js, /document\.querySelectorAll\('\[data-converter-i18n\]'\)/);
assert.match(parent, /window\.MLXI18n\?\.getLanguage\?\.\(\)/);
assert.match(parent, /mlx-language-changed/);
assert.match(parent, /mlx-image-converter-language/);
assert.match(parent, /\/converter\?embedded=1&lang=/);
console.log('Converter bilingual dictionaries and live locale sync contracts passed.');
