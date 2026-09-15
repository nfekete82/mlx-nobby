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
    /id=["']lifecycleProgress["']/,
    'lifecycle modal must contain progress element',
);

assert.match(
    html,
    /id=["']lifecycleProgressBar["']/,
    'lifecycle modal must contain progress bar',
);

assert.match(
    html,
    /id=["']lifecycleProgressText["']/,
    'lifecycle modal must contain progress text',
);

assert.match(
    html,
    /id=["']lifecycleStatusText["']/,
    'lifecycle modal must contain live status text',
);

assert.match(
    js,
    /\/api\/mlx\/system\/lifecycle/,
    'frontend must poll lifecycle status proxy',
);

assert.match(
    js,
    /current/,
    'frontend must consume lifecycle current progress',
);

assert.match(
    js,
    /total/,
    'frontend must consume lifecycle total progress',
);

assert.match(
    js,
    /message/,
    'frontend must consume lifecycle status message',
);

assert.match(
    js,
    /completed/,
    'frontend must handle completed lifecycle state',
);

assert.match(
    js,
    /failed/,
    'frontend must handle failed lifecycle state',
);

assert.match(
    css,
    /\.lifecycle-progress/,
    'lifecycle progress must have dedicated styling',
);

assert.match(
    css,
    /\.lifecycle-progress-bar/,
    'lifecycle progress bar must have dedicated styling',
);

console.log(
    '✓ lifecycle progress UI contract present',
);
