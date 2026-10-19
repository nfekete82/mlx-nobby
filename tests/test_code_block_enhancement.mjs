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



test('code copy uses the same icon and accessible feedback as answer copy', async () => {
    const block = source.match(
        /    \/\/ Use the same icons[\s\S]*?\nfunction enhanceCodeBlocks\(container\) \{[\s\S]*?\n\}/
    );

    assert.ok(block, 'shared copy icons and code enhancer must exist');

    const copied = [];
    const timers = [];
    const buttons = [];
    const context = {
        document: {
            createElement(tag) {
                assert.equal(tag, 'button');
                const button = {
                    attributes: {},
                    setAttribute(key, value) { this.attributes[key] = value; },
                    addEventListener(event, handler) {
                        assert.equal(event, 'click');
                        this.onClick = handler;
                    },
                };
                buttons.push(button);
                return button;
            },
        },
        hljs: { highlightElement() {} },
        navigator: {
            clipboard: {
                async writeText(value) { copied.push(value); },
            },
        },
        setTimeout(callback, delay) {
            assert.equal(delay, 1200);
            timers.push(callback);
        },
    };
    const enhance = vm.runInNewContext(
        block[0] + '\nenhanceCodeBlocks;',
        context
    );

    const pre = {
        tagName: 'PRE',
        isConnected: true,
        children: [],
        querySelector(selector) {
            assert.equal(selector, '.copy-code');
            return this.children.find(item => item.className === 'copy-code');
        },
        appendChild(item) { this.children.push(item); },
    };
    const code = { parentElement: pre, textContent: 'print("Hello")' };
    const container = {
        querySelectorAll(selector) {
            assert.equal(selector, 'pre code');
            return [code];
        },
        contains() { return true; },
    };

    enhance(container);
    enhance(container);
    assert.equal(buttons.length, 1, 're-render must not duplicate copy control');

    const button = pre.children[0];
    assert.equal(button.type, 'button');
    assert.equal(button.title, 'Kopieren');
    assert.equal(button.attributes['aria-label'], 'Kopieren');
    assert.match(button.innerHTML, /<rect x="9" y="9"/);
    assert.doesNotMatch(button.innerHTML, /Kopieren/);

    await button.onClick();
    assert.deepEqual(copied, ['print("Hello")']);
    assert.equal(button.title, 'Kopiert');
    assert.equal(button.attributes['aria-label'], 'Kopiert');
    assert.match(button.innerHTML, /M5 12\.5l4 4L19 6\.5/);

    timers[0]();
    assert.equal(button.title, 'Kopieren');
    assert.equal(button.attributes['aria-label'], 'Kopieren');
    assert.match(button.innerHTML, /<rect x="9" y="9"/);

    context.navigator.clipboard.writeText = async () => {
        throw new Error('Clipboard permissions denied');
    };
    await button.onClick();
    assert.equal(button.title, 'Kopieren',
        'failed clipboard calls must not claim success');
    assert.match(button.innerHTML, /<rect x="9" y="9"/);

    // The under-message action must use the very same icon templates.
    assert.match(source, /copy\.innerHTML = COPY_ICON_SVG;/);
    assert.match(source, /copy\.innerHTML = COPIED_ICON_SVG;/);
});

test('code copy shares compact icon styling with message actions', () => {
    const css = fs.readFileSync(
        new URL('../frontend/assets/chat.css', import.meta.url),
        'utf8'
    );
    assert.match(css, /\.message-actions \.message-action-icon,\s*\.copy-code \{/);
    assert.match(css, /\.message-actions \.message-action-icon svg,\s*\.copy-code svg \{/);
    assert.match(css, /\.copy-code:focus-visible \{/);
});

console.log('Code block enhancement regression passed.');
