import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync(
    'frontend/chat.html',
    'utf8',
);

const js = fs.readFileSync(
    'frontend/assets/chat.js',
    'utf8',
);

const css = fs.readFileSync(
    'frontend/assets/chat.css',
    'utf8',
);

assert.match(
    html,
    /id=["']powerButton["']/,
    'topbar must contain powerButton',
);

assert.match(
    html,
    /id=["']powerMenu["']/,
    'power button must have a menu',
);

assert.match(
    html,
    /data-lifecycle-action=["']reboot["']/,
    'power menu must offer System Reboot',
);

assert.match(
    html,
    /data-lifecycle-action=["']shutdown-ai["']/,
    'power menu must offer AI shutdown',
);

assert.equal(
    (html.match(/data-lifecycle-action=/g) || []).length,
    2,
    'power menu must expose exactly two actions',
);

assert.doesNotMatch(html, /Dienste neu starten|Alles neu bauen/);

assert.match(
    js,
    /\/api\/mlx\/system\//,
    'frontend must call lifecycle proxy',
);

assert.match(
    js,
    /\+\s*action/,
    'frontend must append selected lifecycle action',
);

assert.match(
    js,
    /['"]reboot['"]/,
    'frontend must support reboot',
);

assert.match(
    js,
    /['"]shutdown-ai['"]/,
    'frontend must support AI shutdown',
);

assert.match(js, /shutdown_ai_confirm_active/,
    'AI shutdown must warn when jobs are active');

assert.match(
    js,
    /\/api\/health/,
    'frontend must wait for web health after lifecycle action',
);

assert.match(
    js,
    /location\.reload|window\.location\.reload/,
    'frontend must reload after service recovery',
);

assert.match(
    css,
    /\.power-menu/,
    'power menu must have dedicated styling',
);

console.log('✓ power menu lifecycle contract present');

assert.match(
    html,
    /id=["']confirmModalBusy["']/,
    'lifecycle modal must contain busy state',
);

assert.match(
    html,
    /class=["'][^"']*app-modal-spinner/,
    'lifecycle modal must contain spinner',
);

assert.match(
    js,
    /showConfirmModal/,
    'lifecycle action must use existing confirm modal',
);

assert.match(
    js,
    /showLifecycleBusyModal/,
    'lifecycle action must show working modal after confirmation',
);

assert.match(
    css,
    /@keyframes\s+mlx-nobby-modal-spin/,
    'working modal spinner must be animated',
);
