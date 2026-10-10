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
assert.match(html, /media-library\.js\?v=1-11-library-preview/);
assert.match(html, /media-library\.css\?v=20261010-runtime-modal-layout/);
assert.match(css, /\.nobby-library-panel\[hidden\]/);
assert.match(css, /grid-template-columns:repeat\(auto-fill/);
assert.match(js, /fetch\("\/api\/library\/assets\?limit=1000"/);
assert.match(js, /asset\.kind === "image"/);
assert.match(js, /media\.controls = true/);
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

assert.match(js, /nobby-library-zoom/);
assert.match(js, /showPreview\(asset\)/);
assert.match(js, /previewBody\.replaceChildren\(media\)/);
assert.match(js, /previewBody\.querySelector\("video"\)\?\.pause\(\)/);
assert.match(js, /event\.key === "Escape"/);
assert.doesNotMatch(js, /buttons\.append\(save, remove\)/);
assert.doesNotMatch(js, /t\("Öffnen", "Open"\), false/);
assert.match(js, /buttons\.append\(remove\)/);
assert.match(js, /nobbyLibrarySaveAll/);
assert.match(css, /\.nobby-library-preview\[hidden\]/);
