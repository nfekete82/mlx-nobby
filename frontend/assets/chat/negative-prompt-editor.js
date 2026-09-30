(function () {
    'use strict';

    if (window.__mlxNobbyNegativePromptEditor) return;
    window.__mlxNobbyNegativePromptEditor = true;

    const STORAGE_KEY = 'mlx-nobby-negative-prompt-default-v1';
    const MAX_LENGTH = 2000;
    const FALLBACK = {
        en: {
            helper: 'Preset chips add or remove individual terms. Your custom text stays editable.',
            saveDefault: 'Save as default',
            loadDefault: 'Use default',
            clear: 'Clear',
            saved: 'Default saved.',
            removed: 'Default removed.',
            loaded: 'Default loaded.',
            emptyDefault: 'No saved default yet.'
        },
        de: {}
    };

    let copy = FALLBACK;
    let statusTimer = null;

    function language() {
        const value =
            window.MLXI18n?.getLanguage?.() ||
            window.MLXI18n?.getLocale?.() ||
            navigator.language ||
            'en';
        return String(value).toLowerCase().startsWith('de') ? 'de' : 'en';
    }

    function t(key) {
        return copy[language()]?.[key] || copy.en?.[key] || FALLBACK.en[key] || key;
    }

    async function loadTranslations() {
        try {
            const response = await fetch('/i18n/negative-prompt-editor.json', {
                cache: 'no-cache'
            });
            if (!response.ok) throw new Error('HTTP ' + response.status);
            const payload = await response.json();
            if (payload?.de && payload?.en) copy = payload;
        } catch (error) {
            console.warn('[negative-prompt-editor] translations unavailable', error);
        }
    }

    function parseTerms(value) {
        return String(value || '')
            .split(/[,;\n]+/)
            .map(term => term.trim())
            .filter(Boolean);
    }

    function termKey(value) {
        return String(value || '').trim().toLocaleLowerCase();
    }

    function uniqueTerms(terms) {
        const seen = new Set();
        const result = [];

        for (const term of terms) {
            const clean = String(term || '').trim();
            const key = termKey(clean);
            if (!clean || seen.has(key)) continue;
            seen.add(key);
            result.push(clean);
        }

        return result;
    }

    function serializeTerms(terms) {
        return uniqueTerms(terms).join(', ').slice(0, MAX_LENGTH).trim();
    }

    function presetTerms(button) {
        return uniqueTerms(
            parseTerms(button?.dataset?.negativePromptPreset || '')
        );
    }

    function containsPreset(value, button) {
        const current = new Set(parseTerms(value).map(termKey));
        const preset = presetTerms(button);
        return Boolean(preset.length) && preset.every(term => current.has(termKey(term)));
    }

    function togglePreset(value, button) {
        const current = uniqueTerms(parseTerms(value));
        const preset = presetTerms(button);
        const currentKeys = new Set(current.map(termKey));
        const allPresent = Boolean(preset.length) &&
            preset.every(term => currentKeys.has(termKey(term)));

        if (allPresent) {
            const remove = new Set(preset.map(termKey));
            return serializeTerms(current.filter(term => !remove.has(termKey(term))));
        }

        return serializeTerms([
            ...current,
            ...preset.filter(term => !currentKeys.has(termKey(term)))
        ]);
    }

    function readDefault() {
        try {
            return String(localStorage.getItem(STORAGE_KEY) || '').trim().slice(0, MAX_LENGTH);
        } catch (_) {
            return '';
        }
    }

    function writeDefault(value) {
        const normalized = String(value || '').trim().slice(0, MAX_LENGTH);
        try {
            if (normalized) {
                localStorage.setItem(STORAGE_KEY, normalized);
            } else {
                localStorage.removeItem(STORAGE_KEY);
            }
        } catch (_) {}
        return normalized;
    }

    function setInputValue(input, value) {
        input.value = String(value || '').slice(0, MAX_LENGTH);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
    }

    function presetButtons() {
        return [
            ...document.querySelectorAll('[data-negative-prompt-preset]')
        ];
    }

    function updatePresetState(input) {
        for (const button of presetButtons()) {
            const active = containsPreset(input.value, button);
            button.classList.toggle('is-selected', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        }
    }

    function showStatus(root, message) {
        const status = root.querySelector('[data-negative-prompt-status]');
        if (!status) return;
        clearTimeout(statusTimer);
        status.textContent = message;
        status.hidden = false;
        statusTimer = setTimeout(() => {
            status.hidden = true;
            status.textContent = '';
        }, 1800);
    }

    function updateDefaultButton(root) {
        const button = root.querySelector('[data-negative-prompt-load-default]');
        if (button) button.disabled = !readDefault();
    }

    function ensureControls() {
        const field = document.getElementById('imageNegativePromptField');
        const input = document.getElementById('imageNegativePrompt');
        const presets = field?.querySelector('.media-negative-prompt-presets');
        if (!field || !input || !presets) return null;

        input.maxLength = MAX_LENGTH;

        let root = field.querySelector('[data-negative-prompt-editor-controls]');
        if (!root) {
            root = document.createElement('div');
            root.className = 'negative-prompt-editor-controls';
            root.dataset.negativePromptEditorControls = 'true';

            const helper = document.createElement('div');
            helper.className = 'negative-prompt-editor-helper';
            helper.dataset.negativePromptHelper = 'true';

            const actions = document.createElement('div');
            actions.className = 'negative-prompt-editor-actions';

            const save = document.createElement('button');
            save.type = 'button';
            save.dataset.negativePromptSaveDefault = 'true';

            const load = document.createElement('button');
            load.type = 'button';
            load.dataset.negativePromptLoadDefault = 'true';

            const clear = document.createElement('button');
            clear.type = 'button';
            clear.dataset.negativePromptClear = 'true';

            const status = document.createElement('span');
            status.className = 'negative-prompt-editor-status';
            status.dataset.negativePromptStatus = 'true';
            status.hidden = true;

            actions.append(save, load, clear, status);
            root.append(helper, actions);
            presets.after(root);

            save.addEventListener('click', () => {
                const saved = writeDefault(input.value);
                updateDefaultButton(root);
                showStatus(root, saved ? t('saved') : t('removed'));
            });

            load.addEventListener('click', () => {
                const saved = readDefault();
                if (!saved) {
                    showStatus(root, t('emptyDefault'));
                    return;
                }
                setInputValue(input, saved);
                showStatus(root, t('loaded'));
            });

            clear.addEventListener('click', () => {
                setInputValue(input, '');
            });

            input.addEventListener('input', () => updatePresetState(input));
        }

        root.querySelector('[data-negative-prompt-helper]').textContent = t('helper');
        root.querySelector('[data-negative-prompt-save-default]').textContent = t('saveDefault');
        root.querySelector('[data-negative-prompt-load-default]').textContent = t('loadDefault');
        root.querySelector('[data-negative-prompt-clear]').textContent = t('clear');

        updateDefaultButton(root);
        updatePresetState(input);
        return { field, input, root };
    }

    function applySavedDefaultWhenEmpty() {
        const ui = ensureControls();
        if (!ui || ui.field.hidden || ui.input.value.trim()) return;

        const saved = readDefault();
        if (saved) setInputValue(ui.input, saved);
    }

    function onPresetClick(event) {
        const button = event.target?.closest?.('[data-negative-prompt-preset]');
        if (!button) return;

        const field = button.closest('#imageNegativePromptField');
        const input = document.getElementById('imageNegativePrompt');
        if (!field || !input || field.hidden) return;

        // generation.js historically replaces the whole textarea on preset click.
        // Capture the click first so custom text is preserved and the preset can toggle.
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        setInputValue(input, togglePreset(input.value, button));
    }

    function observeModal() {
        const modal = document.getElementById('mediaQualityModal');
        if (!modal) return;

        const observer = new MutationObserver(() => {
            if (!modal.hidden && modal.getAttribute('aria-hidden') !== 'true') {
                queueMicrotask(applySavedDefaultWhenEmpty);
            }
        });

        observer.observe(modal, {
            attributes: true,
            attributeFilter: ['hidden', 'aria-hidden']
        });
    }

    async function start() {
        await loadTranslations();
        ensureControls();
        observeModal();

        document.addEventListener('click', onPresetClick, true);
        document.addEventListener('mlx-language-changed', () => {
            loadTranslations().then(ensureControls);
        });
    }

    window.MLXNegativePromptEditor = {
        parseTerms,
        togglePreset,
        containsPreset,
        readDefault,
        writeDefault
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
