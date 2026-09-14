import assert from 'node:assert/strict';
import fs from 'node:fs';

const chatHtml = fs.readFileSync(
    new URL('../frontend/chat.html', import.meta.url),
    'utf8',
);

const chatJs = fs.readFileSync(
    new URL('../frontend/assets/chat.js', import.meta.url),
    'utf8',
);

const sessionsJs = fs.readFileSync(
    new URL('../frontend/assets/chat/sessions.js', import.meta.url),
    'utf8',
);

assert.match(
    chatHtml,
    /id="confirmModal"/,
);

assert.match(
    chatHtml,
    /id="confirmModalConfirm"/,
);

assert.match(
    chatHtml,
    /id="confirmModalCancel"/,
);

assert.match(
    chatJs,
    /window\.MLXConfirm\s*=\s*showConfirmModal/,
);

assert.match(
    sessionsJs,
    /async function deleteMessages\(\)/,
);

assert.match(
    sessionsJs,
    /await confirmFn\(\{/,
);

const deleteMessagesStart =
    sessionsJs.indexOf('async function deleteMessages()');

const updateTitleStart =
    sessionsJs.indexOf(
        'function updateTitle(session)',
        deleteMessagesStart,
    );

assert.notEqual(deleteMessagesStart, -1);
assert.notEqual(updateTitleStart, -1);

const deleteMessagesBlock =
    sessionsJs.slice(
        deleteMessagesStart,
        updateTitleStart,
    );

assert.doesNotMatch(
    deleteMessagesBlock,
    /(^|[^A-Za-z])confirm\s*\(/,
);

assert.match(
    deleteMessagesBlock,
    /delete session\.workspace\.active_artifact_id;/,
);

assert.match(
    deleteMessagesBlock,
    /if \(!Object\.keys\(session\.workspace\)\.length\)/,
);

assert.match(
    deleteMessagesBlock,
    /const resetResult = await response\.json\(\)/,
);

assert.match(
    deleteMessagesBlock,
    /session\.revision = revision/,
);

console.log(
    'Confirm modal: markup, helper, async clear-chat flow, and native confirm removal passed.'
);
