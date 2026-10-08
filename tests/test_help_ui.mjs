import assert from 'node:assert/strict';
import fs from 'node:fs';

const common = fs.readFileSync('frontend/assets/common.js', 'utf8');
const help = fs.readFileSync('frontend/assets/chat/help.js', 'utf8');
const chatHtml = fs.readFileSync('frontend/chat.html', 'utf8');
const dockerfile = fs.readFileSync('Dockerfile', 'utf8');

assert.match(common, /\/assets\/chat\/help\.js\?v=20261008-finance-help-v2/);
assert.match(common, /mlx-help-center/);
assert.match(common, /frontendBuildRevision/);
assert.match(common, /versionedAssetUrl/);
assert.match(common, /searchParams\.set\('build', frontendBuildRevision\)/);
assert.match(common, /mlxHelpVisibilityFix/);
assert.match(common, /\.mlx-help-panel\[hidden\]\{display:none!important;\}/);
assert.match(common, /mlxTopbarActionCleanup/);
assert.match(common, /#settingsButton,#mlxHelpButton\{display:none!important;\}/);
assert.match(common, /getElementById\('settingsButton'\)\?\.remove\(\)/);
assert.match(common, /getElementById\('mlxHelpButton'\)\?\.remove\(\)/);
assert.match(chatHtml, /id="sidebarSettingsButton"/);
assert.match(dockerfile, /common\.js\?v=\$\{MLX_NOBBY_BUILD_SHA\}/);

for (const topic of [
    'getting-started',
    'images',
    'finance',
    'video',
    'shorts',
    'voice',
    'agent',
    'knowledge',
    'models',
    'troubleshooting'
]) {
    assert.match(help, new RegExp(`id: '${topic}'`));
}

assert.match(help, /id = 'mlxHelpButton'/);
assert.match(help, /id = 'mlxSidebarHelpButton'/);
assert.match(help, /id = 'mlxHelpPanel'/);
assert.match(help, /id = 'mlxHelpSearch'/);
assert.match(help, /function insertPrompt\(prompt\)/);
assert.match(help, /input\.dispatchEvent\(new Event\('input'/);
assert.match(help, /document\.addEventListener\('mlx-language-changed', refreshCopy\)/);
assert.match(help, /document\.addEventListener\('mlx-i18n-ready', refreshCopy\)/);
assert.match(help, /Render Short/);
assert.match(help, /mlx doctor/);
assert.match(help, /\.\/scripts\/restart-all\.sh/);
assert.match(help, /window\.MLXHelp/);

console.log('Integrated help stays available in the sidebar while redundant topbar actions are removed.');
