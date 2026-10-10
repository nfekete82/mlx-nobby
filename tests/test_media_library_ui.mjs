import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');
const js = fs.readFileSync(new URL('../frontend/assets/chat/media-library.js', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../frontend/assets/chat/media-library.css', import.meta.url), 'utf8');

assert.match(html, /id="sidebarLibraryButton"/);
assert.match(html, /id="railLibrary"/);
assert.match(html, /id="nobbyLibrary"/);
assert.match(html, /id="nobbyLibraryGrid"/);
assert.match(html, /id="nobbyLibrarySaveAll"/);
assert.match(html, /media-library\.js\?v=1-10-0/);
assert.match(html, /media-library\.css\?v=1-11-6/);
assert.match(css, /\.nobby-library-panel\[hidden\]/);
assert.match(css, /grid-template-columns:repeat\(auto-fill/);
assert.match(js, /fetch\("\/api\/library\/assets\?limit=1000"/);
assert.match(js, /asset\.kind === "image"/);
assert.match(js, /video\.controls = true/);
assert.match(js, /window\.confirm/);
assert.match(js, /encodeURIComponent\(asset\.id\)/);
assert.match(js, /new Date\(Number\(value\) \* 1000\)/);
assert.doesNotMatch(js, /innerHTML\s*=/, 'Use safe DOM nodes for asset data');

console.log('Media library sidebar, gallery, browse, download, save and delete contracts passed.');

assert.match(html, /id="nobbyLibraryDeleteAll"/);
assert.match(html, /nobby-new-chat-action/);
assert.match(js, /DELETE_ALL_MEDIA_PERMANENTLY/);
assert.match(js, /\/api\/library\/assets\/delete-all/);
assert.match(css, /nobby-library-danger/);
