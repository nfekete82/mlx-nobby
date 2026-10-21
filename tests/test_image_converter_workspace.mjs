import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');
const nav = fs.readFileSync(new URL('../frontend/assets/chat/sidebar-rail-utilities.js', import.meta.url), 'utf8');
const controller = fs.readFileSync(new URL('../frontend/assets/chat/image-converter-workspace.js', import.meta.url), 'utf8');
const style = fs.readFileSync(new URL('../frontend/assets/chat/image-converter-workspace.css', import.meta.url), 'utf8');
const embedded = fs.readFileSync(new URL('../frontend/converter.html', import.meta.url), 'utf8');
const embeddedCSS = fs.readFileSync(new URL('../frontend/assets/image-converter.css', import.meta.url), 'utf8');

assert.match(html, /id="imageConverterButton"/);
assert.match(html, /id="imageConverterWorkspace"/);
assert.match(html, /id="imageConverterFrame"/);
assert.match(html, /id="imageConverterBack"/);
assert.match(html, /image-converter-workspace\.js\?v=1-0/);
assert.match(nav, /\['imageConverterButton', 'railImageConverter', 'Bildkonverter'\]/);
assert.match(controller, /\/converter\?embedded=1/);
assert.match(controller, /if \(!frame\.getAttribute\('src'\)\)/);
assert.match(controller, /panel\.hidden = false/);
assert.match(controller, /panel\.hidden = true/);
assert.match(controller, /#newChat/);
assert.match(controller, /#talkingPhotoButton/);
assert.match(controller, /\.mlx-shorts-history-launcher/);
assert.match(style, /body\.mlx-image-converter-open \.composer-wrap/);
assert.match(style, /\.mlx-image-converter-workspace\[hidden\]/);
assert.match(embedded, /URLSearchParams\(location\.search\)/);
assert.match(embeddedCSS, /html\.converter-embedded/);
assert.doesNotMatch(controller, /createSession|deleteSession|replaceChildren\(.*messages|window\.location\s*=/);
console.log('Inline image converter sidebar, icon rail, embedded workspace and chat preservation contracts passed.');
