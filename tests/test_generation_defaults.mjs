import fs from 'node:fs';
import assert from 'node:assert/strict';

const runtime = fs.readFileSync(
    'frontend/assets/chat/runtime.js',
    'utf8'
);

const html = fs.readFileSync(
    'frontend/chat.html',
    'utf8'
);

assert.match(
    runtime,
    /function persistCurrentGenerationDefaults\(settings\)/
);

assert.match(
    runtime,
    /globalSettings\.default_system_prompt\s*=/
);

assert.match(
    runtime,
    /globalSettings\.default_temperature\s*=/
);

assert.match(
    runtime,
    /globalSettings\.default_max_tokens\s*=/
);

const presetBlock =
    runtime.slice(
        runtime.indexOf('function handlePresetChange'),
        runtime.indexOf('function handleSystemPromptInput')
    );

assert.match(
    presetBlock,
    /persistCurrentGenerationDefaults\(settings\);/
);

const inputBlock =
    runtime.slice(
        runtime.indexOf('function handleSystemPromptInput'),
        runtime.indexOf('function getSessionSystemPrompt')
    );

assert.match(
    inputBlock,
    /persistCurrentGenerationDefaults\(settings\);/
);

assert.doesNotMatch(
    html,
    /id="saveGenerationDefaults"/
);

assert.doesNotMatch(
    runtime,
    /saveCurrentGenerationDefaults/
);

assert.doesNotMatch(
    runtime,
    /saveGenerationDefaultsStatus/
);

assert.match(
    html,
    /id="defaultPreset"/
);

assert.match(
    html,
    /id="defaultTemperature"/
);

assert.match(
    html,
    /id="defaultMaxTokens"/
);

console.log(
    'Generation defaults: current chat settings auto-save as new-chat defaults.'
);
