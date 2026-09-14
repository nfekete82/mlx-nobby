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
    /id=["']activeWorkspaceHeader["']/,
    'header must contain activeWorkspaceHeader',
);

assert.match(
    html,
    /id=["']activeWorkspaceHeaderButton["']/,
    'header must contain clickable workspace selector',
);

assert.match(
    html,
    /id=["']activeWorkspaceHeaderClose["']/,
    'header must contain workspace close button',
);

assert.match(
    js,
    /activeWorkspaceHeader/,
    'frontend must render workspace state into header',
);

assert.match(
    js,
    /\/api\/mlx\/code\/workspaces\/pick/,
    'header workspace selector must reuse existing folder picker',
);

assert.match(
    js,
    /\/api\/mlx\/code\/workspaces\/active/,
    'frontend must use active-workspace API',
);

assert.match(
    js,
    /DELETE|deactivate/,
    'frontend must support closing/deactivating active workspace',
);

assert.match(
    css,
    /\.active-workspace-header/,
    'workspace header must have dedicated styling',
);

console.log('✓ workspace header contract present');
