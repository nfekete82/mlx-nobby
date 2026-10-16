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
assert.match(html, /media-library\.js\?v=1-17-search/);
assert.match(html, /media-library\.css\?v=[a-z0-9-]+/);
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

assert.match(html, /id="nobbyLibraryEngine"/);
assert.match(js, /state\.engine === "all"/);
assert.match(js, /thumbnailUrl\(asset\)/);
assert.match(js, /metadataUrl\(asset\)/);
assert.match(js, /IntersectionObserver/);
assert.match(js, /window\.MLXTalkingPhoto\.openWithImage\(file,/);
assert.match(css, /nobby-library-engine-field/);
assert.match(css, /nobby-library-media-details/);
assert.doesNotMatch(js, /innerHTML\s*=/, "Do not interpolate filenames or engine names into HTML");
console.log("Library 2.0: lazy preview, engine filtering and Talking Photo reuse contracts passed.");

assert.match(html, /id="nobbyLibraryCollectionFilter"/);
assert.match(html, /id="nobbyLibraryCollectionTarget"/);
assert.match(html, /id="nobbyLibrarySelectVisible"/);
assert.match(html, /id="nobbyLibraryBulk"/);
assert.match(js, /\/api\/library\/organize\/batch/);
assert.match(js, /\/api\/library\/organize\/collections/);
assert.match(js, /nobby-library-star/);
assert.match(js, /nobby-library-select/);
assert.match(js, /visibleAssets\(\)/);
assert.match(js, /state\.selected\.add/);
assert.match(css, /\.nobby-library-bulk\[hidden\]/);
assert.match(css, /\.nobby-library-star/);
console.log("Library 3.0: persistent favorites, collections and bulk-selection UI contracts passed.");

assert.match(js, /createVideoFromImage\(asset\)/);
assert.match(js, /window\.MLXChatAttachments\.addFiles\(\[file\]\)/);
assert.match(js, /attachment\.library_source\s*=/);
assert.match(js, /fetch\("\/api\/library\/workflows"/);
assert.match(js, /nobby-library-parent-link/);
assert.match(js, /mediaLineage\(asset/);
assert.match(css, /\.nobby-library-parent-link/);
assert.match(html, /generation\.js\?v=1-16-media-studio/);
console.log("Media Studio 1.16: source-to-video composer and provenance UI contracts passed.");

assert.match(html,/id="nobbyLibraryDateFilter"/);
assert.match(html,/id="nobbyLibrarySort"/);
assert.match(js,/state\.dateFilter === "today"/);
assert.match(js,/state\.sort === "largest"/);
console.log("Library 1.17 date and size sorting controls passed.");

const de = JSON.parse(fs.readFileSync(new URL('../frontend/i18n/de.json', import.meta.url), 'utf8'));
const en = JSON.parse(fs.readFileSync(new URL('../frontend/i18n/en.json', import.meta.url), 'utf8'));
assert.equal(de["library.more_actions"], "Weitere Aktionen");
assert.equal(en["library.more_actions"], "More actions");
assert.match(html, /nobby-library-primary-row/);
assert.match(html, /nobby-library-secondary-row/);
assert.match(html, /nobby-library-action-row/);
assert.match(html, /nobby-library-more-menu/);
assert.match(html, /<details class="nobby-library-more">[\s\S]*?<button id="nobbyLibraryDeleteAll"/);
assert.ok(html.indexOf('id="nobbyLibrarySearch"') < html.indexOf('id="nobbyLibraryDateFilter"'));
assert.ok(html.indexOf('id="nobbyLibrarySort"') < html.indexOf('id="nobbyLibrarySelectVisible"'));
assert.ok(html.indexOf('id="nobbyLibrarySelectVisible"') < html.indexOf('id="nobbyLibraryDeleteAll"'));
assert.match(html, /media-library\.css\?v=1-17-dropdown-polish/);
assert.match(css, /\.nobby-library-secondary-row\{/);
assert.match(css, /@media\(max-width:560px\)/);
assert.match(css, /\.nobby-library-more-menu \[hidden\]\{display:none!important\}/);
console.log("Library toolbar grouping, responsive filters, and protected actions contract passed.");


assert.match(css, /@supports \(appearance:base-select\) and selector\(::picker\(select\)\)/);
assert.match(css, /select::picker\(select\)/);
assert.match(css, /width:anchor-size\(width\)/);
assert.match(css, /select option:checked/);
assert.match(css, /color-scheme:dark/);
for (const id of ["nobbyLibraryCollectionFilter","nobbyLibraryEngine","nobbyLibraryDateFilter","nobbyLibrarySort"]) {
  assert.equal((html.match(new RegExp('id="' + id + '"', 'g')) || []).length, 1);
}
console.log("Library select popups share a dark browser-native dropdown style.");
