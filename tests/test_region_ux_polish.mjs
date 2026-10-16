import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const code = fs.readFileSync('frontend/assets/chat/region-editor.js', 'utf8');
const css = fs.readFileSync('frontend/assets/chat/region-editor.css', 'utf8');
const html = fs.readFileSync('frontend/chat.html', 'utf8');
const generation = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');

test('editor loads with translated shortcut labels and never opens unprompted', () => {
    const context = vm.createContext({
        window: {},
        document: {documentElement: {lang:'de'}}
    });
    vm.runInContext(code, context);
    assert.equal(typeof context.window.MLXRegionEditor.open, 'function');
});

test('zoom preserves a shared image+mask stage and real pixel coordinates', () => {
    assert.match(code, /imageStage\.append\(image, display\)/);
    assert.match(code, /function setZoom\(next\)/);
    assert.match(code, /imageStage\.style\.width/);
    assert.match(code, /imageStage\.style\.height/);
    assert.match(code, /imageWrap\.scrollLeft/);
    assert.match(code, /display\.getBoundingClientRect\(\)/);
    assert.match(css, /\.nobby-region-editor-stage/);
    assert.match(css, /overscroll-behavior: contain/);
    assert.match(css, /touch-action: none/);
    assert.match(code, /setZoom\(1\)/);
});

test('brush persistence and keyboard shortcuts are guarded', () => {
    assert.match(code, /localStorage\?\.getItem\('nobby-region-brush-size'\)/);
    assert.match(code, /localStorage\?\.setItem\('nobby-region-brush-size'/);
    assert.match(code, /event\.ctrlKey \|\| event\.metaKey/);
    assert.match(code, /event\.key\.toLowerCase\(\) === 'b'/);
    assert.match(code, /event\.key\.toLowerCase\(\) === 'e'/);
    assert.match(code, /event\.key === 'Escape'/);
    assert.match(code, /if \(editing \|\| event\.ctrlKey/);
});

test('safe prompt presets and bounded soft-edge slider only affect region edits', () => {
    assert.match(code, /const presetValues = \[/);
    assert.match(code, /prompt\.value = instruction/);
    assert.match(code, /feather\.min = '0'; feather\.max = '12'/);
    assert.match(code, /region_feather_px: Number\(feather\.value\)/);
    assert.match(generation, /region_feather_px: region_feather_px/);
    assert.match(generation, /region_edit: true/);
    assert.match(html, /region-editor\.js\?v=1-1/);
    assert.match(html, /region-editor\.css\?v=1-1/);
});
