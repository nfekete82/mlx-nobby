import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = fs.readFileSync(
    new URL(
        '../frontend/assets/chat/rendering.js',
        import.meta.url
    ),
    'utf8'
);

test('enhanceCodeBlocks tolerates missing container', () => {
    const match = source.match(
        /function enhanceCodeBlocks\(container\) \{[\s\S]*?\n\}/
    );

    assert.ok(
        match,
        'enhanceCodeBlocks() must exist'
    );

    assert.match(
        match[0],
        /if \(!container\) return;/,
        'missing container must be guarded'
    );
});

test('enhanceCodeBlocks guards detached code blocks', () => {
    assert.match(
        source,
        /const pre = code\.parentElement;/,
        'parent must be captured'
    );

    assert.match(
        source,
        /if \(!pre \|\| pre\.tagName !== 'PRE'\)/,
        'missing parent must be guarded'
    );

    assert.match(
        source,
        /!pre\.isConnected && !container\.contains\(pre\)/,
        'detached parent must be guarded'
    );
});

console.log(
    'Code block enhancement null-parent regression passed.'
);
