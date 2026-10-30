import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = readFileSync(
    new URL('../frontend/assets/chat/image-count-picker.js', import.meta.url), 'utf8'
);
const storageKey = 'mlx-nobby-image-generation-count-v1';

function createPicker(storageMap, storageDisabled = false) {
    const listeners = new Map();
    const dom = new Map();

    function element(tag = 'div') {
        const node = {
            tagName: tag.toUpperCase(),
            children: [],
            hidden: false,
            value: '',
            textContent: '',
            parentNode: null,
            append(...children) { children.forEach(child => this.appendChild(child)); },
            appendChild(child) {
                child.parentNode = this;
                this.children.push(child);
                return child;
            },
            setAttribute() {},
            addEventListener(type, handler) {
                listeners.set(this, {...(listeners.get(this) || {}), [type]: handler});
            }
        };
        return node;
    }

    const modal = element();
    modal.hidden = true;
    const confirm = element('button');
    const negativeField = element();
    negativeField.hidden = true;
    const formatField = element();
    const parent = element();
    parent.insertBefore = child => parent.appendChild(child);
    parent.appendChild(formatField);

    dom.set('mediaQualityModal', modal);
    dom.set('mediaQualityModalConfirm', confirm);
    dom.set('imageNegativePromptField', negativeField);
    dom.set('mediaFormatField', formatField);
    const document = {
        readyState: 'loading',
        documentElement: {lang: 'de'},
        getElementById(id) {
            if (dom.has(id)) return dom.get(id);
            function find(node) {
                if (node.id === id) return node;
                for (const child of node.children) {
                    const result = find(child);
                    if (result) return result;
                }
                return null;
            }
            return find(parent);
        },
        createElement: element,
        addEventListener() {}
    };

    const window = {
        addEventListener() {},
        localStorage: {
            getItem(key) {
                if (storageDisabled) throw new Error('Storage blocked');
                return storageMap.get(key) ?? null;
            },
            setItem(key, value) {
                if (storageDisabled) throw new Error('Storage blocked');
                storageMap.set(key, value);
            }
        }
    };
    const context = { window, document, console,
        fetch: async () => ({ok: false}), MutationObserver: undefined,
        setTimeout() {return 1;}, clearTimeout() {}, Map, Date, Math,
        Number, String, Object,
    };
    vm.runInNewContext(source, context, { filename: 'image-count-picker.js' });
    assert.equal(window.MLXImageCountPicker.install(), true);
    const helper = window.MLXImageCountPicker.__test;
    const pickerField = document.getElementById('imageVariantCountField');
    const select = document.getElementById('imageVariantCount');

    function openImageModal() {
        negativeField.hidden = false;
        modal.hidden = false;
        helper.syncPickerVisibility();
        assert.equal(pickerField.hidden, false);
    }
    function closeModal() {
        modal.hidden = true;
        helper.syncPickerVisibility();
    }
    function choose(count) {
        select.value = String(count);
        listeners.get(select).change({target: select});
    }
    function confirmSelection() {
        listeners.get(confirm).click({target: confirm});
    }
    return {openImageModal,closeModal,choose,confirmSelection,select,storageMap,helper};
}

test('new installation starts at 1, then remembers each manually chosen count', () => {
    const store = new Map();
    const picker = createPicker(store);
    picker.openImageModal();
    assert.equal(picker.select.value, '1');
    picker.choose(4);
    assert.equal(store.get(storageKey), '4');
    picker.closeModal();
    picker.openImageModal();
    assert.equal(picker.select.value, '4', 'reopening must not reset to one');

    picker.choose(2);
    picker.confirmSelection();
    assert.equal(store.get(storageKey), '2');
    picker.closeModal();
    picker.openImageModal();
    assert.equal(picker.select.value, '2');
});

test('new chat/page initialization uses saved count and keeps it across reloads', () => {
    const store = new Map([[storageKey, '6']]);
    let picker = createPicker(store);
    picker.openImageModal();
    assert.equal(picker.select.value, '6');
    picker.choose(3);
    picker = createPicker(store);
    picker.openImageModal();
    assert.equal(picker.select.value, '3');
});

test('invalid storage values fall back safely without persisting an unwanted reset', () => {
    for (const invalid of ['NaN', '7', '-1', '0', '1.5', '']) {
        const store = new Map([[storageKey, invalid]]);
        const picker = createPicker(store);
        picker.openImageModal();
        assert.equal(picker.select.value, '1');
        assert.equal(store.get(storageKey), invalid);
    }
});

test('localStorage errors do not break the selector within the same page', () => {
    const picker = createPicker(new Map(), true);
    picker.openImageModal();
    picker.choose(5);
    picker.closeModal();
    picker.openImageModal();
    assert.equal(picker.select.value, '5');
});

test('video-only dialogs do not expose or reset image count', () => {
    const store = new Map([[storageKey, '4']]);
    const picker = createPicker(store);
    // The initial dialog is hidden. Its visibility synchronization must not
    // mutate the count even if modal state changes for a non-image operation.
    picker.helper.syncPickerVisibility();
    assert.equal(store.get(storageKey), '4');
    picker.openImageModal();
    assert.equal(picker.select.value, '4');
});
