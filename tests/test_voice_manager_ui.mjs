import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const manager = fs.readFileSync(
    new URL('../frontend/assets/chat/voice-manager.js', import.meta.url),
    'utf8'
);
const common = fs.readFileSync(
    new URL('../frontend/assets/common.js', import.meta.url),
    'utf8'
);
const translations = JSON.parse(fs.readFileSync(
    new URL('../frontend/i18n/voice-manager.json', import.meta.url),
    'utf8'
));
const speechRoutes = fs.readFileSync(
    new URL('../speech/voice_manager_routes.py', import.meta.url),
    'utf8'
);
const agentRoutes = fs.readFileSync(
    new URL('../agent/voice_manager_routes.py', import.meta.url),
    'utf8'
);
const backendRoutes = fs.readFileSync(
    new URL('../backend/voice_manager_routes.py', import.meta.url),
    'utf8'
);


test('Voice Manager is loaded after the voice picker', () => {
    assert.match(common, /\/assets\/chat\/voice\.js/);
    assert.match(common, /\/assets\/chat\/voice-manager\.js/);
    assert.ok(
        common.indexOf('/assets/chat/voice.js') < common.indexOf('/assets/chat/voice-manager.js')
    );
});


test('Voice Manager exposes the full local management workflow', () => {
    assert.match(manager, /\/api\/mlx\/audio\/voices\/manage/);
    assert.match(manager, /\/api\/mlx\/audio\/voices\/import/);
    assert.match(manager, /\/api\/mlx\/audio\/voice-default/);
    assert.match(manager, /method: 'DELETE'/);
    assert.match(manager, /method: 'PUT'/);
    assert.match(manager, /FormData\(\)/);
    assert.match(manager, /MLXVoice\?\.setVoice/);
    assert.match(manager, /MLXVoiceStreaming\?\.clearCache/);
});


test('Voice Manager translations have matching German and English keys', () => {
    assert.deepEqual(
        Object.keys(translations.de).sort(),
        Object.keys(translations.en).sort()
    );
    assert.equal(translations.de.quality_natural, 'Natürlich');
    assert.equal(translations.en.quality_natural, 'Natural');
});


test('speech service keeps voice storage local and validates managed paths', () => {
    assert.match(speechRoutes, /TTS_VOICES_DIR/);
    assert.match(speechRoutes, /candidate\.is_symlink\(\)/);
    assert.match(speechRoutes, /resolved_parent != root/);
    assert.match(speechRoutes, /VOICE_UPLOAD_MAX_BYTES/);
    assert.match(speechRoutes, /os\.replace\(temporary_dir, final_dir\)/);
    assert.match(speechRoutes, /shutil\.rmtree\(profile_dir\)/);
});


test('voice manager routes are proxied through agent and web layers', () => {
    for (const source of [agentRoutes, backendRoutes]) {
        assert.match(source, /\/api\/mlx\/audio\/voices\/manage/);
        assert.match(source, /\/api\/mlx\/audio\/voices\/import/);
        assert.match(source, /\/api\/mlx\/audio\/voice-default/);
        assert.match(source, /\/api\/mlx\/audio\/voices\/\{voice\}/);
    }
});
