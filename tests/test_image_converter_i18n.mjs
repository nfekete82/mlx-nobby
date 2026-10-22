import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync('frontend/converter.html', 'utf8');
const js = fs.readFileSync('frontend/assets/image-converter.js', 'utf8');
const parent = fs.readFileSync('frontend/assets/chat/image-converter-workspace.js', 'utf8');

for (const key of ['header', 'heading', 'intro', 'drop', 'format', 'png', 'quality',
  'maxEdge', 'original', 'alpha', 'submit', 'footer']) {
  assert.match(html, new RegExp('data-converter-i18n="' + key + '"'), key);
  assert.match(js, new RegExp('\\b' + key + ': '), key);
}
assert.match(html, /<html lang="en">/);
assert.match(js, /document\.documentElement\.lang = language/);
assert.match(js, /window\.addEventListener\('message'/);
assert.match(js, /if \(event\.origin !== location\.origin \|\| event\.source !== window\.parent\)/);
assert.match(js, /document\.querySelectorAll\('\[data-converter-i18n\]'\)/);
assert.match(parent, /window\.MLXI18n\?\.getLanguage\?\.\(\)/);
assert.match(parent, /mlx-language-changed/);
assert.match(parent, /mlx-image-converter-language/);
assert.match(parent, /\/converter\?embedded=1&lang=/);
assert.doesNotMatch(parent, /frame\.setAttribute\('src', '[^']+' \+ selectedLanguage\(\)\);\s*else/);
console.log('Converter bilingual contracts and cross-frame locale synchronization passed.');
