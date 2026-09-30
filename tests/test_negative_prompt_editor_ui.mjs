import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const editor = fs.readFileSync(
    new URL('../frontend/assets/chat/negative-prompt-editor.js', import.meta.url),
    'utf8'
);
const styles = fs.readFileSync(
    new URL('../frontend/assets/chat/negative-prompt-editor.css', import.meta.url),
    'utf8'
);
const middleware = fs.readFileSync(
    new URL('../backend/negative_prompt_ui.py', import.meta.url),
    'utf8'
);
const translations = JSON.parse(fs.readFileSync(
    new URL('../frontend/i18n/negative-prompt-editor.json', import.meta.url),
    'utf8'
));


test('negative prompt presets preserve custom text and toggle terms', () => {
    assert.match(editor, /function togglePreset/);
    assert.match(editor, /stopImmediatePropagation\(\)/);
    assert.match(editor, /setInputValue\(input, togglePreset\(input\.value, button\)\)/);
    assert.doesNotMatch(
        editor,
        /input\.value\s*=\s*String\(\s*event\.currentTarget\.dataset\.negativePromptPreset/
    );
});


test('negative prompt editor persists an optional global default', () => {
    assert.match(editor, /mlx-nobby-negative-prompt-default-v1/);
    assert.match(editor, /localStorage\.setItem/);
    assert.match(editor, /localStorage\.removeItem/);
    assert.match(editor, /if \(!ui \|\| ui\.field\.hidden \|\| ui\.input\.value\.trim\(\)\) return;/);
    assert.match(editor, /save\.dataset\.negativePromptSaveDefault/);
    assert.match(editor, /load\.dataset\.negativePromptLoadDefault/);
    assert.match(editor, /clear\.dataset\.negativePromptClear/);
});


test('negative prompt editor is injected as isolated chat assets', () => {
    assert.match(middleware, /negative-prompt-editor\.js/);
    assert.match(middleware, /negative-prompt-editor\.css/);
    assert.match(styles, /media-negative-prompt-presets button\.is-selected/);
});


test('negative prompt translations stay aligned in German and English', () => {
    assert.deepEqual(
        Object.keys(translations.de).sort(),
        Object.keys(translations.en).sort()
    );
    assert.equal(translations.de.saveDefault, 'Als Standard speichern');
    assert.equal(translations.en.saveDefault, 'Save as default');
});
