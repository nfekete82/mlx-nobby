import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
    new URL('../frontend/assets/chat/rendering.js', import.meta.url),
    'utf8',
);

const document = {
    getElementById() {
        return {};
    },
    createElement() {
        return {
            textContent: '',
            get innerHTML() {
                return this.textContent
                    .replaceAll('&', '&amp;')
                    .replaceAll('<', '&lt;')
                    .replaceAll('>', '&gt;');
            },
        };
    },
    addEventListener() {},
    querySelectorAll() {
        return [];
    },
};

const marked = {
    parse(value) {
        return `<p>${value}</p>`;
    },
    parseInline(value) {
        return value;
    },
};

const DOMPurify = {
    sanitize(value) {
        return value;
    },
};

const katex = {
    renderToString(value, options = {}) {
        const mode = options.displayMode
            ? 'display'
            : 'inline';

        return `<math data-mode="${mode}">${value}</math>`;
    },
};

const window = {
    MLXI18n: {
        t(_key, fallback) {
            return fallback;
        },
    },
};

window.window = window;

const context = {
    console,
    document,
    window,
    marked,
    DOMPurify,
    katex,
};

vm.runInNewContext(source, context, {
    filename: 'frontend/assets/chat/rendering.js',
});

const render =
    window.MLXChatRendering.__test.markdownHtml;

assert.match(
    render('$a^2+b^2=c^2$'),
    /<math data-mode="inline">a\^2\+b\^2=c\^2<\/math>/,
);

assert.match(
    render('$$\\frac{a}{b}$$'),
    /<math data-mode="display">\\frac\{a\}\{b\}<\/math>/,
);

assert.match(
    render('\\(x^2\\)'),
    /<math data-mode="inline">x\^2<\/math>/,
);

assert.match(
    render('\\[x^2\\]'),
    /<math data-mode="display">x\^2<\/math>/,
);

const inlineCode = render('`$foo`');

assert.doesNotMatch(
    inlineCode,
    /<math/,
);

assert.match(
    inlineCode,
    /\$foo/,
);

const fencedCode = render(
    '```php\n$price = 10;\n```'
);

assert.doesNotMatch(
    fencedCode,
    /<math/,
);

assert.match(
    fencedCode,
    /\$price = 10;/,
);

console.log(
    'Math rendering: inline, display, delimiters, and code protection passed.'
);
